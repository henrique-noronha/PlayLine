"""Rotas de biblioteca, mídia, thumbnails e upload."""

import asyncio
import hashlib
import logging
import mimetypes
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response

from core import settings as app_settings
from api.helpers import _ffmpeg_bin, _NO_WINDOW, _settings_error

logger = logging.getLogger(__name__)

router = APIRouter()

_manager = None


def setup(manager):
    global _manager
    _manager = manager


_MEDIA_EXTS = {
    ".mp4", ".avi", ".mov", ".mkv", ".mts", ".m2ts", ".mxf",
    ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts",
    ".mp3", ".wav", ".aac", ".m4a",
}

_THUMB_CACHE_DIR: Path = (
    Path(sys.executable).parent / "cache" / "thumbs"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent.parent / "cache" / "thumbs"
)

_LIBRARY_DEFAULT: Path = (
    Path(sys.executable).parent / "Biblioteca"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent.parent / "Biblioteca"
)


def _initial_library_base() -> Path:
    """Pasta configurada em config.json, ou a padrão (criada se preciso)."""
    cfg = app_settings.get_library_dir()
    if cfg is not None:
        if cfg.is_dir():
            return cfg
        logger.warning("Pasta da biblioteca configurada não encontrada (%s); usando %s",
                       cfg, _LIBRARY_DEFAULT)
    _LIBRARY_DEFAULT.mkdir(exist_ok=True)
    return _LIBRARY_DEFAULT


_LIBRARY_BASE: Path = _initial_library_base()


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


def _scan_media(path: Path) -> list[dict]:
    return sorted(
        [{"name": f.stem, "filename": f.name, "path": str(f)}
         for f in path.iterdir()
         if f.is_file() and f.suffix.lower() in _MEDIA_EXTS],
        key=lambda x: x["filename"].lower(),
    )


# ── Mídia ──────────────────────────────────────────────────────────────────

@router.get("/media")
async def serve_media(path: str):
    p = _validate_path(path, _MEDIA_EXTS)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    mime, _ = mimetypes.guess_type("x" + p.suffix.lower())
    return FileResponse(str(p), media_type=mime or "video/mp4")


# ── Thumbnails ─────────────────────────────────────────────────────────────

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
                "-vf", "scale=112:63:force_original_aspect_ratio=increase,crop=112:63",
                "-f", "image2", "-vcodec", "mjpeg", "pipe:1",
            ],
            capture_output=True,
            timeout=15,
            creationflags=_NO_WINDOW,
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
    await asyncio.sleep(1)

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
        await asyncio.sleep(0.05)

    logger.info("[prewarm] %d thumbnail(s) gerado(s) em cache", warmed)


# ── Biblioteca ─────────────────────────────────────────────────────────────

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
        files = _scan_media(_LIBRARY_BASE)
        for sub in sorted(_LIBRARY_BASE.iterdir()):
            if sub.is_dir():
                files += _scan_media(sub)
    return {"files": files}


_UPLOAD_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".ts", ".mxf", ".mpg", ".mpeg", ".wmv", ".flv", ".webm"}
_MIN_FREE_MB  = 200
_UPLOAD_CHUNK = 1024 * 1024


@router.post("/api/upload")
async def upload_file(subfolder: str = "", file: UploadFile = File(...)):
    """Recebe um arquivo de mídia e salva na Biblioteca (subpasta indicada)."""
    import errno as _errno
    import shutil

    safe_name = Path(file.filename).name
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    ext = Path(safe_name).suffix.lower()
    if ext not in _UPLOAD_EXTS:
        raise HTTPException(status_code=415, detail=f"Extensão não suportada: {ext}")

    if subfolder:
        if ".." in subfolder or "/" in subfolder or "\\" in subfolder:
            raise HTTPException(status_code=400, detail="Subfolder inválido")
        dest_dir = _LIBRARY_BASE / subfolder
        if not dest_dir.is_dir():
            raise HTTPException(status_code=404, detail="Subpasta não encontrada")
    else:
        dest_dir = _LIBRARY_BASE

    try:
        free_mb = shutil.disk_usage(dest_dir).free // (1024 * 1024)
        if free_mb < _MIN_FREE_MB:
            raise HTTPException(
                status_code=507,
                detail=f"Disco quase cheio no servidor — apenas {free_mb} MB livres (mínimo exigido: {_MIN_FREE_MB} MB)"
            )
    except HTTPException:
        raise
    except Exception:
        pass

    dest = dest_dir / safe_name
    if not dest.resolve().is_relative_to(dest_dir.resolve()):
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    suffix = 1
    while dest.exists():
        dest = dest_dir / f"{Path(safe_name).stem}_{suffix}{ext}"
        suffix += 1

    try:
        total = 0
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                f.write(chunk)
        if total == 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Arquivo vazio")
    except HTTPException:
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        if exc.errno == _errno.ENOSPC:
            raise HTTPException(status_code=507, detail="Disco cheio no servidor — sem espaço para salvar o arquivo")
        elif exc.errno in (_errno.EACCES, _errno.EPERM):
            raise HTTPException(
                status_code=403,
                detail="Acesso negado ao salvar o arquivo — um antivírus ou política de segurança pode estar bloqueando a gravação na pasta Biblioteca"
            )
        else:
            raise HTTPException(status_code=500, detail=f"Erro de sistema ao salvar arquivo: {exc}")
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"ok": True, "saved_as": dest.name, "path": str(dest)}


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


@router.delete("/api/library/folder")
async def delete_library_folder(subfolder: str):
    """Remove uma subpasta vazia da Biblioteca."""
    if ".." in subfolder or "/" in subfolder or "\\" in subfolder:
        raise HTTPException(status_code=400, detail="Nome inválido")
    target = _LIBRARY_BASE / subfolder
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    try:
        target.rmdir()
    except OSError:
        raise HTTPException(status_code=409, detail="A pasta não está vazia")
    return {"deleted": subfolder}


# ── Troca de pasta da biblioteca ───────────────────────────────────────────

@router.post("/api/settings/library")
async def change_library_dir(body: dict):
    """Troca a pasta da biblioteca em runtime e persiste em config.json."""
    global _LIBRARY_BASE
    loop = asyncio.get_running_loop()
    if body.get("reset"):
        new = _LIBRARY_DEFAULT
        await loop.run_in_executor(None, lambda: new.mkdir(exist_ok=True))
        app_settings.set_library_dir(None)
    else:
        try:
            new = await loop.run_in_executor(
                None, app_settings.validate_library_dir, str(body.get("path") or ""))
        except ValueError as exc:
            return _settings_error(exc)
        app_settings.set_library_dir(new)
    changed = new != _LIBRARY_BASE
    _LIBRARY_BASE = new
    if changed:
        logger.info("Biblioteca alterada para %s", new)
        if _manager:
            await _manager.broadcast({"event": "library_changed", "library_dir": str(new)})
        asyncio.create_task(prewarm_thumbnails())
    return {"ok": True, "library_dir": str(new), "changed": changed}
