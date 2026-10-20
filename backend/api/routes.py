"""Rotas HTTP do PlayLine — agregador de sub-routers + schedule/playback/settings."""

import asyncio
import logging
import subprocess

from fastapi import APIRouter, HTTPException

from core import settings as app_settings
from api.helpers import _coded_error, _settings_error, _ffmpeg_bin, _NO_WINDOW
from api import library_routes, cities_routes, logo_routes

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(library_routes.router)
router.include_router(cities_routes.router)
router.include_router(logo_routes.router)

# Re-exports para backward compat (main.py importa estes nomes)
prewarm_thumbnails = library_routes.prewarm_thumbnails

_playlist_engine = None
_manager = None


def setup(playlist_engine, manager):
    global _playlist_engine, _manager
    _playlist_engine = playlist_engine
    _manager = manager
    library_routes.setup(manager)
    cities_routes.setup(manager)


# ── Playback / Schedule ───────────────────────────────────────────────────

@router.post("/api/stop")
async def stop_playback():
    """Para a reprodução atual e para a engine de playlist."""
    if _playlist_engine is None:
        raise HTTPException(status_code=503, detail="Servidor não inicializado")
    await _playlist_engine.stop()
    return {"ok": True}


@router.get("/api/history")
async def get_history(date: str = "", limit: int = 200):
    return {"entries": _playlist_engine._history.get_history(date or None, limit)}


@router.get("/api/history/stats")
async def get_history_stats():
    return _playlist_engine._history.get_stats()


@router.get("/api/schedule")
async def get_schedule():
    return _playlist_engine.get_schedule()


@router.put("/api/schedule")
async def update_schedule(items: list[dict]):
    _playlist_engine.save_schedule(items, from_ui=True)
    await _manager.broadcast({"event": "schedule_updated", "items": items})
    return {"ok": True}


@router.get("/api/state")
async def get_state():
    return _playlist_engine.state()


@router.post("/api/repeat")
async def set_repeat(body: dict):
    enabled = bool(body.get("enabled", False))
    _playlist_engine.set_repeat(enabled)
    return {"repeat": enabled}


# ── Configurações ─────────────────────────────────────────────────────────

@router.get("/api/settings")
async def get_settings():
    """Usuário atual e pasta da biblioteca (atual, padrão e configurada)."""
    cfg = app_settings.get_library_dir()
    loop = asyncio.get_running_loop()
    missing = (await loop.run_in_executor(None, cfg.is_dir) is False) if cfg is not None else False
    return {
        "username": app_settings.get_username(),
        "library_dir": str(library_routes._LIBRARY_BASE),
        "library_default": str(library_routes._LIBRARY_DEFAULT),
        "library_configured": str(cfg) if cfg else "",
        "library_missing": missing,
        "transition": app_settings.get_transition(),
    }


@router.post("/api/settings/transition")
async def change_transition(body: dict):
    """Transição global. O modal só altera a duração; o tipo é o botão do cabeçalho do roteiro (WS)."""
    if _playlist_engine is None:
        return _coded_error(503, "engine_unavailable", "Engine indisponível")
    try:
        cfg = await _playlist_engine.set_transition({k: body[k] for k in ("type", "duration") if k in body})
    except ValueError as exc:
        return _settings_error(exc)
    return {"ok": True, "transition": cfg}


# ── YouTube ───────────────────────────────────────────────────────────────

@router.get("/api/youtube/info")
async def youtube_info(url: str):
    """Valida URL do YouTube e retorna título e flag is_live."""
    url = (url or "").strip()
    try:
        from core.youtube_resolver import is_youtube_url, get_info
    except ImportError:
        try:
            from ..core.youtube_resolver import is_youtube_url, get_info
        except ImportError:
            return _coded_error(501, "yt_unavailable", "yt-dlp não disponível")
    if not url or not is_youtube_url(url):
        return _coded_error(400, "yt_invalid_url", "URL do YouTube inválida")
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, get_info, url)
    if not info.get("valid"):
        return _coded_error(422, info.get("code", "yt_info_failed"),
                            info.get("error", "Não foi possível obter informações"),
                            **info.get("params", {}))
    return info


# ── MPV ───────────────────────────────────────────────────────────────────

@router.post("/api/mpv/quit")
async def quit_mpv():
    """Encerra o player MPV (daemon continua ativo). Bloqueado durante reprodução."""
    if _playlist_engine is None:
        raise HTTPException(status_code=503, detail="Servidor não inicializado")
    if _playlist_engine._running:
        raise HTTPException(status_code=409, detail="Pare a reprodução antes de encerrar o player")
    _playlist_engine._player.quit_mpv()
    return {"ok": True}


@router.post("/api/mpv/init")
async def init_mpv():
    """Inicializa (ou reinicializa) o player MPV sem reproduzir nada."""
    if _playlist_engine is None:
        raise HTTPException(status_code=503, detail="Servidor não inicializado")
    _playlist_engine._player.init_mpv()
    return {"ok": True}


# ── Roteiros salvos ──────────────────────────────────────────────────────

@router.get("/api/saved-schedules")
async def list_saved_schedules():
    from core import saved_schedules as ss
    return {"schedules": ss.list_saved()}


@router.post("/api/saved-schedules")
async def create_saved_schedule(body: dict):
    title = (body.get("title") or "").strip()
    items = body.get("items") or []
    if not title:
        return _coded_error(400, "schedule_title_required", "Título obrigatório")
    from core import saved_schedules as ss
    new_id = ss.save(title, items)
    return {"id": new_id}


@router.delete("/api/saved-schedules/{schedule_id}")
async def delete_saved_schedule(schedule_id: int):
    from core import saved_schedules as ss
    if not ss.delete(schedule_id):
        raise HTTPException(status_code=404, detail="Roteiro não encontrado")
    return {"ok": True}


@router.get("/api/saved-schedules/{schedule_id}/items")
async def get_saved_schedule_items(schedule_id: int):
    from core import saved_schedules as ss
    items = ss.get_items(schedule_id)
    if items is None:
        raise HTTPException(status_code=404, detail="Roteiro não encontrado")
    return {"items": items}


# ── Dispositivos de captura ──────────────────────────────────────────────

def _list_capture_devices_sync() -> dict:
    """Enumera dispositivos DirectShow via ffmpeg (bloqueante, chamar via run_in_executor)."""
    import re
    ffmpeg = _ffmpeg_bin()
    logger.info("capture-devices: usando ffmpeg em %r", ffmpeg)
    try:
        result = subprocess.run(
            [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        raw = result.stderr.decode("utf-8", errors="replace")
        logger.info("capture-devices stderr:\n%s", raw)
        devices = []
        for line in raw.splitlines():
            if "(video)" in line:
                m = re.search(r'"([^"]+)"', line)
                if m:
                    name = m.group(1)
                    if name not in devices:
                        devices.append(name)
        logger.info("capture-devices encontrados: %s", devices)
        return {"devices": devices}
    except Exception as exc:
        logger.warning("capture-devices error: %s", exc)
        return {"devices": [], "error": str(exc)}


@router.get("/api/capture-devices")
async def list_capture_devices():
    """Lista dispositivos de vídeo DirectShow disponíveis (webcams, placas de captura)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _list_capture_devices_sync)
