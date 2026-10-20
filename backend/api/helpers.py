"""Utilitários compartilhados entre os sub-routers da API."""

import sys

from fastapi.responses import JSONResponse


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _coded_error(status: int, code: str, detail: str, **params) -> JSONResponse:
    """Erro com código estável para a interface traduzir (dicionário 'apierr')."""
    return JSONResponse(status_code=status,
                        content={"detail": detail, "code": code, "params": params})


def _settings_error(exc: ValueError, status: int = 400) -> JSONResponse:
    return _coded_error(status, getattr(exc, "code", "invalid_value"), str(exc),
                        **getattr(exc, "params", {}))


def _ffmpeg_bin() -> str:
    from pathlib import Path
    if getattr(sys, "frozen", False):
        local = Path(sys._MEIPASS) / "ffmpeg.exe"
        if local.is_file():
            return str(local)
    local_dev = Path(__file__).parent.parent / "ffmpeg.exe"
    if local_dev.is_file():
        return str(local_dev)
    return "ffmpeg"
