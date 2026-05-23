"""Rotas HTTP do PlayLine."""

import mimetypes
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

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
    _playlist_engine.save_schedule(items)
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
