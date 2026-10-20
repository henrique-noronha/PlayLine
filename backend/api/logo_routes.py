"""Rotas de logo (upload, listagem, servir por slot)."""

import io
import logging
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_LOGO_WORK_DIR = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "pltmp"

_LOGOS_STATIC_DIR = (
    Path(sys.executable).parent / "logos"
    if getattr(sys, 'frozen', False)
    else Path(__file__).parent.parent / "logos"
)

_MAX_LOGO_BYTES = 5 * 1024 * 1024  # 5 MB


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
