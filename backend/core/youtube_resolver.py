"""Resolução de streams do YouTube via yt-dlp."""

import logging
import re

logger = logging.getLogger(__name__)

_YT_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch|live)|youtu\.be/)"
)


def is_youtube_url(url: str) -> bool:
    return bool(_YT_RE.search(url))


def get_info(url: str) -> dict:
    """Retorna metadados básicos sem baixar o stream."""
    try:
        import yt_dlp
    except ImportError:
        return {"valid": False, "error": "yt-dlp não instalado"}
    try:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get("title") or "Live do YouTube",
                "is_live": bool(info.get("is_live")),
                "valid": True,
            }
    except Exception as exc:
        logger.warning("get_info falhou: %s", exc)
        return {"valid": False, "error": str(exc)}


def get_stream_url(url: str) -> str:
    """Resolve URL do YouTube para URL HLS/MPEG-TS direta via yt-dlp."""
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp não instalado")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[ext=mp4]/best",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Tenta URL direta primeiro (live streams retornam manifest HLS aqui)
    direct = info.get("url")
    if direct:
        return direct

    # Fallback: primeiro formato selecionado
    fmts = info.get("requested_formats") or []
    if fmts and fmts[0].get("url"):
        return fmts[0]["url"]

    raise RuntimeError(f"yt-dlp não retornou URL de stream para: {url}")
