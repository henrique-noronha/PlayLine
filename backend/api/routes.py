"""Rotas HTTP do PlayLine."""

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


@router.get("/api/thumbnail")
async def get_thumbnail(path: str):
    p = _validate_path(path, _MEDIA_EXTS)
    if not p.is_file():
        raise HTTPException(status_code=404)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-ss", "2", "-i", str(p),
                "-vframes", "1",
                "-vf", "scale=112:63:force_original_aspect_ratio=decrease,pad=112:63:(ow-iw)/2:(oh-ih)/2:color=black",
                "-f", "image2", "-vcodec", "mjpeg", "pipe:1",
            ],
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            return Response(content=result.stdout, media_type="image/jpeg")
    except FileNotFoundError:
        pass  # ffmpeg não instalado
    except Exception as exc:
        logger.warning("Thumbnail ffmpeg error: %s", exc)
    raise HTTPException(status_code=404, detail="Thumbnail não disponível")


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


@router.get("/api/library")
async def get_library(folder: str = ""):
    if not folder:
        return {"files": []}
    if not Path(folder).is_absolute() or any(part == ".." for part in Path(folder).parts):
        raise HTTPException(status_code=400, detail="Caminho inválido")
    p = Path(folder)
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Pasta não encontrada")
    files = sorted(
        [
            {"name": f.stem, "filename": f.name, "path": str(f)}
            for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in _MEDIA_EXTS
        ],
        key=lambda x: x["filename"].lower(),
    )
    return {"folder": str(p), "files": files}
