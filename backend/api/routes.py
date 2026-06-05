"""Rotas HTTP do PlayLine."""

import io
import mimetypes
import logging
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response

# Mesmo caminho usado pelo mpv_daemon — sem espaços para compatibilidade com lavfi
_LOGO_WORK_DIR = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "pltmp"

logger = logging.getLogger(__name__)

router = APIRouter()

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
    p = Path(path)
    if p.suffix.lower() not in _MEDIA_EXTS:
        raise HTTPException(status_code=403, detail="Tipo de arquivo não permitido")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    mime, _ = mimetypes.guess_type("x" + p.suffix.lower())
    return FileResponse(str(p), media_type=mime or "video/mp4")


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

_LOGOS_STATIC_DIR = Path(__file__).parent.parent / "logos"


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


@router.post("/api/logo/{slot}")
async def upload_logo(slot: int, file: UploadFile = File(...)):
    """Recebe um PNG, redimensiona para padrão emissora e salva no dir de trabalho."""
    if slot not in (1, 2):
        raise HTTPException(status_code=400, detail="Slot inválido (use 1 ou 2)")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Apenas imagens são aceitas")
    try:
        from PIL import Image
        data = await file.read()
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
    p = Path(path)
    if p.suffix.lower() not in _MEDIA_EXTS:
        raise HTTPException(status_code=403)
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


@router.get("/api/library")
async def get_library(folder: str = ""):
    if not folder:
        return {"files": []}
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
