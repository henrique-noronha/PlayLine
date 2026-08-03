"""Rotas HTTP do PlayLine."""

import hashlib
import io
import mimetypes
import logging
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response

# Mesmo caminho usado pelo mpv_daemon — sem espaços para compatibilidade com lavfi
_LOGO_WORK_DIR = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "pltmp"

logger = logging.getLogger(__name__)

router = APIRouter()

_THUMB_CACHE_DIR: Path = (
    Path(sys.executable).parent / "cache" / "thumbs"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent.parent / "cache" / "thumbs"
)


def _validate_path(path: str, allowed_exts: set) -> Path:
    """Valida que o caminho é absoluto, sem traversal (..) e com extensão permitida."""
    if not path:
        raise HTTPException(status_code=400, detail="Caminho vazio")
    p = Path(path)
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="Caminho deve ser absoluto")
    if any(part == ".." for part in p.parts):
        raise HTTPException(status_code=400, detail="Caminho inválido")
    if p.suffix.lower() not in allowed_exts:
        raise HTTPException(status_code=403, detail="Tipo de arquivo não permitido")
    return p


_MEDIA_EXTS = {
    ".mp4", ".avi", ".mov", ".mkv", ".mts", ".m2ts", ".mxf",
    ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts",
    ".mp3", ".wav", ".aac", ".m4a",
}

_playlist_engine = None
_manager = None


def setup(playlist_engine, manager):
    global _playlist_engine, _manager
    _playlist_engine = playlist_engine
    _manager = manager


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


@router.get("/media")
async def serve_media(path: str):
    p = _validate_path(path, _MEDIA_EXTS)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    mime, _ = mimetypes.guess_type("x" + p.suffix.lower())
    return FileResponse(str(p), media_type=mime or "video/mp4")


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

_LOGOS_STATIC_DIR = (
    Path(sys.executable).parent / "logos"
    if getattr(sys, 'frozen', False)
    else Path(__file__).parent.parent / "logos"
)


@router.get("/api/logos")
async def list_logos():
    """Lista os arquivos de logo disponíveis na pasta logos/."""
    try:
        files = sorted(
            f.name for f in _LOGOS_STATIC_DIR.iterdir()
            if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg"}
        )
    except Exception:
        files = []
    return {"files": files}


@router.get("/api/logos/{filename}")
async def get_logo_static(filename: str):
    """Serve um arquivo de logo da pasta estática logos/ (para preview na interface)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    p = _LOGOS_STATIC_DIR / filename
    if not p.is_file() or p.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=404, detail="Logo não encontrado")
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(str(p), media_type=mime)


_MAX_LOGO_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/api/logo/{slot}")
async def upload_logo(slot: int, file: UploadFile = File(...)):
    """Recebe um PNG, redimensiona para padrão emissora e salva no dir de trabalho."""
    if slot not in (1, 2):
        raise HTTPException(status_code=400, detail="Slot inválido (use 1 ou 2)")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Apenas imagens são aceitas")
    try:
        from PIL import Image
        data = await file.read(_MAX_LOGO_BYTES + 1)
        if len(data) > _MAX_LOGO_BYTES:
            raise HTTPException(status_code=413, detail="Arquivo muito grande (limite 5 MB)")
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        target_h = 90
        if img.height != target_h:
            ratio = target_h / img.height
            img = img.resize((max(1, int(img.width * ratio)), target_h), Image.LANCZOS)
        _LOGO_WORK_DIR.mkdir(parents=True, exist_ok=True)
        work = _LOGO_WORK_DIR / f"l{slot}.png"
        img.save(str(work), "PNG")
        logger.info("Logo %d salvo: %s (%dx%d)", slot, work, img.width, img.height)
        return {"ok": True, "slot": slot, "name": file.filename, "w": img.width, "h": img.height}
    except Exception as exc:
        logger.error("Erro ao salvar logo %d: %s", slot, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/logo/{slot}")
async def get_logo_slot(slot: int):
    """Serve o arquivo de trabalho do logo (para preview na interface)."""
    if slot not in (1, 2):
        raise HTTPException(status_code=400)
    work = _LOGO_WORK_DIR / f"l{slot}.png"
    if not work.is_file():
        raise HTTPException(status_code=404, detail="Logo não enviado ainda")
    return FileResponse(str(work), media_type="image/png")


def _ffmpeg_bin() -> str:
    if getattr(sys, "frozen", False):
        local = Path(sys._MEIPASS) / "ffmpeg.exe"
        if local.is_file():
            return str(local)
    return "ffmpeg"


def _thumb_cache_file(path: str) -> Path:
    key = hashlib.md5(path.encode()).hexdigest()
    return _THUMB_CACHE_DIR / f"{key}.jpg"


def _generate_thumb(path: str) -> bytes | None:
    """Gera thumbnail via ffmpeg. Retorna bytes JPEG ou None em caso de falha."""
    try:
        result = subprocess.run(
            [
                _ffmpeg_bin(), "-y", "-ss", "2", "-i", path,
                "-vframes", "1",
                "-vf", "scale=112:63:force_original_aspect_ratio=decrease,pad=112:63:(ow-iw)/2:(oh-ih)/2:color=black",
                "-f", "image2", "-vcodec", "mjpeg", "pipe:1",
            ],
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("Thumbnail ffmpeg error: %s", exc)
    return None


@router.get("/api/thumbnail")
async def get_thumbnail(path: str):
    p = _validate_path(path, _MEDIA_EXTS)
    if not p.is_file():
        raise HTTPException(status_code=404)

    cache_file = _thumb_cache_file(path)
    _CACHE_HEADERS = {"Cache-Control": "public, max-age=604800, immutable"}
    if cache_file.is_file():
        return FileResponse(str(cache_file), media_type="image/jpeg", headers=_CACHE_HEADERS)

    import asyncio
    data = await asyncio.get_event_loop().run_in_executor(None, _generate_thumb, path)
    if data:
        try:
            _THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(data)
        except Exception:
            pass
        return Response(content=data, media_type="image/jpeg", headers=_CACHE_HEADERS)
    raise HTTPException(status_code=404, detail="Thumbnail não disponível")


async def prewarm_thumbnails() -> None:
    """Gera thumbnails em cache para todos os arquivos da biblioteca durante o startup."""
    import asyncio
    await asyncio.sleep(1)  # aguarda o servidor estabilizar

    loop = asyncio.get_event_loop()

    def _collect():
        files = []
        try:
            for f in _LIBRARY_BASE.rglob("*"):
                if f.is_file() and f.suffix.lower() in _MEDIA_EXTS:
                    files.append(f)
        except Exception:
            pass
        return files

    files = await loop.run_in_executor(None, _collect)
    logger.info("[prewarm] %d arquivo(s) encontrado(s) na biblioteca", len(files))

    warmed = 0
    for f in files:
        cache_file = _thumb_cache_file(str(f))
        if cache_file.is_file():
            continue

        def _gen(src=f, dst=cache_file):
            data = _generate_thumb(str(src))
            if data:
                try:
                    _THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(data)
                except Exception:
                    pass
                return True
            return False

        ok = await loop.run_in_executor(None, _gen)
        if ok:
            warmed += 1
        await asyncio.sleep(0.05)  # ~20 por segundo — não bloqueia o event loop

    logger.info("[prewarm] %d thumbnail(s) gerado(s) em cache", warmed)


@router.get("/api/temperature")
async def get_temperature(city: str = "Palmas,TO"):
    """Proxy para OpenWeatherMap — retorna temperatura como texto (ex: '24°C')."""
    import asyncio, json
    from urllib.request import urlopen
    from urllib.parse import quote
    from fastapi.responses import PlainTextResponse

    _API_KEY = "f69ea9de2f716268934177c04852b89b"

    def _fetch():
        import logging
        log = logging.getLogger("api.routes")
        owm_name = city.split(",")[0].strip()  # OWM: só cidade, sem estado
        # Tenta OpenWeatherMap primeiro
        try:
            url  = f"https://api.openweathermap.org/data/2.5/weather?q={quote(owm_name)},BR&appid={_API_KEY}&units=metric"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                temp = data.get("main", {}).get("temp")
                if temp is not None:
                    found   = data.get("name", "?")
                    country = data.get("sys", {}).get("country", "?")
                    log.info("[weather] OWM: %.1f°C (%s, %s)", temp, found, country)
                    return f"{round(temp)}°C"
        except Exception as e:
            log.warning("[weather] OWM falhou: %s — tentando wttr.in", e)
        # Fallback: wttr.in — usa cidade completa com estado para evitar ambiguidade
        try:
            url = f"https://wttr.in/{quote(city)}?format=%t"
            with urlopen(url, timeout=5) as resp:
                val = resp.read().decode("utf-8").strip().lstrip("+")
                log.info("[weather] wttr.in fallback: %s", val)
                return val
        except Exception as e:
            log.warning("[weather] wttr.in também falhou: %s", e)
            return ""

    loop = asyncio.get_running_loop()
    val = await loop.run_in_executor(None, _fetch)
    return PlainTextResponse(val or "—")


# ── Biblioteca estruturada ──────────────────────────────────────────────────

_LIBRARY_BASE: Path = (
    Path(sys.executable).parent / "Biblioteca"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent.parent / "Biblioteca"
)
_LIBRARY_BASE.mkdir(exist_ok=True)


def _scan_media(path: Path) -> list[dict]:
    return sorted(
        [{"name": f.stem, "filename": f.name, "path": str(f)}
         for f in path.iterdir()
         if f.is_file() and f.suffix.lower() in _MEDIA_EXTS],
        key=lambda x: x["filename"].lower(),
    )


@router.get("/api/library")
async def get_library_info():
    """Retorna as subpastas da Biblioteca."""
    subfolders = sorted(f.name for f in _LIBRARY_BASE.iterdir() if f.is_dir())
    return {"subfolders": subfolders, "base": str(_LIBRARY_BASE)}


@router.get("/api/library/files")
async def get_library_files(subfolder: str = ""):
    """Retorna arquivos de mídia de uma subpasta ou de toda a Biblioteca."""
    if subfolder:
        if ".." in subfolder or "/" in subfolder or "\\" in subfolder:
            raise HTTPException(status_code=400, detail="Subfolder inválido")
        target = _LIBRARY_BASE / subfolder
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="Pasta não encontrada")
        files = _scan_media(target)
    else:
        # Todos: raiz + todas as subpastas
        files = _scan_media(_LIBRARY_BASE)
        for sub in sorted(_LIBRARY_BASE.iterdir()):
            if sub.is_dir():
                files += _scan_media(sub)
    return {"files": files}


@router.post("/api/library/folder")
async def create_library_folder(body: dict):
    """Cria uma nova subpasta na Biblioteca."""
    name = (body.get("name") or "").strip()
    if not name or ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Nome inválido")
    ((_LIBRARY_BASE / name)).mkdir(exist_ok=True)
    return {"created": name}


@router.patch("/api/library/folder")
async def rename_library_folder(body: dict):
    """Renomeia uma subpasta da Biblioteca."""
    old = (body.get("old") or "").strip()
    new = (body.get("new") or "").strip()
    for v in (old, new):
        if not v or ".." in v or "/" in v or "\\" in v:
            raise HTTPException(status_code=400, detail="Nome inválido")
    src = _LIBRARY_BASE / old
    dst = _LIBRARY_BASE / new
    if not src.is_dir():
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    if dst.exists():
        raise HTTPException(status_code=409, detail="Já existe uma pasta com esse nome")
    try:
        src.rename(dst)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Erro ao renomear: {e}")
    return {"renamed": {"old": old, "new": new}}


@router.get("/api/youtube/info")
async def youtube_info(url: str):
    """Valida URL do YouTube e retorna título e flag is_live."""
    import asyncio
    url = (url or "").strip()
    try:
        from core.youtube_resolver import is_youtube_url, get_info
    except ImportError:
        try:
            from ..core.youtube_resolver import is_youtube_url, get_info
        except ImportError:
            raise HTTPException(status_code=501, detail="yt-dlp não disponível")
    if not url or not is_youtube_url(url):
        raise HTTPException(status_code=400, detail="URL do YouTube inválida")
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, get_info, url)
    if not info.get("valid"):
        raise HTTPException(status_code=422, detail=info.get("error", "Não foi possível obter informações"))
    return info


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


# ── Roteiros salvos ────────────────────────────────────────────────────────

@router.get("/api/saved-schedules")
async def list_saved_schedules():
    from core import saved_schedules as ss
    return {"schedules": ss.list_saved()}


@router.post("/api/saved-schedules")
async def create_saved_schedule(body: dict):
    title = (body.get("title") or "").strip()
    items = body.get("items") or []
    if not title:
        raise HTTPException(status_code=400, detail="Título obrigatório")
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


@router.delete("/api/library/folder")
async def delete_library_folder(subfolder: str):
    """Remove uma subpasta vazia da Biblioteca."""
    if ".." in subfolder or "/" in subfolder or "\\" in subfolder:
        raise HTTPException(status_code=400, detail="Nome inválido")
    target = _LIBRARY_BASE / subfolder
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    try:
        target.rmdir()  # só remove se estiver vazia
    except OSError:
        raise HTTPException(status_code=409, detail="A pasta não está vazia")
    return {"deleted": subfolder}
