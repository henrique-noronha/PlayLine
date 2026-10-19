"""Resolução de streams do YouTube via yt-dlp para URL HLS direta."""

import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

_YT_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch|live)|youtu\.be/)"
)

# Pré-importa yt_dlp na inicialização do módulo para evitar ~0.5 s de penalidade
# na primeira chamada de get_stream_url.
try:
    import yt_dlp as _yt_dlp
except ImportError:
    _yt_dlp = None


def is_youtube_url(url: str) -> bool:
    return bool(_YT_RE.search(url))


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def _starts_in(unit_code: str, unit_pt: str):
    """Mensagem "Esta live começa em N <unidade>" com singular/plural no código."""
    def build(m):
        n = int(m.group(1))
        plural = n != 1
        return (f"{unit_code}_{'many' if plural else 'one'}",
                f"Esta live começa em {n} {unit_pt}{'s' if plural else ''}", {"n": n})
    return build


_YT_ERROR_MAP = [
    (re.compile(r"live event will begin in (\d+) hour",  re.I), _starts_in("yt_starts_hours", "hora")),
    (re.compile(r"live event will begin in (\d+) minute", re.I), _starts_in("yt_starts_minutes", "minuto")),
    (re.compile(r"live event will begin in (\d+) day",   re.I), _starts_in("yt_starts_days", "dia")),
    (re.compile(r"private video",                        re.I), lambda m: ("yt_private", "Vídeo privado", {})),
    (re.compile(r"video unavailable",                    re.I), lambda m: ("yt_video_unavailable", "Vídeo indisponível", {})),
    (re.compile(r"members.only",                         re.I), lambda m: ("yt_members_only", "Conteúdo exclusivo para membros", {})),
    (re.compile(r"confirm your age",                     re.I), lambda m: ("yt_age_restricted", "Restrição de idade", {})),
    (re.compile(r"copyright",                            re.I), lambda m: ("yt_copyright", "Conteúdo bloqueado por direitos autorais", {})),
]

def _friendly_error(exc: Exception) -> tuple[str, str, dict]:
    """(code, mensagem em português, params) para um erro do yt-dlp."""
    raw = _ANSI_RE.sub("", str(exc))
    for pattern, build in _YT_ERROR_MAP:
        m = pattern.search(raw)
        if m:
            return build(m)
    # Remove prefixo "ERROR: [youtube] ID: " deixando só a mensagem
    clean = re.sub(r"^ERROR:\s*\[youtube\]\s*[A-Za-z0-9_-]+:\s*", "", raw).strip()
    if clean:
        return "yt_other", clean, {"reason": clean}
    return "yt_info_failed", "Não foi possível obter informações do vídeo", {}


def get_info(url: str) -> dict:
    """Retorna metadados básicos sem baixar o stream."""
    if _yt_dlp is None:
        return {"valid": False, "error": "yt-dlp não instalado", "code": "yt_unavailable", "params": {}}
    try:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with _yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get("title") or "Live do YouTube",
                "is_live": bool(info.get("is_live")),
                "valid": True,
            }
    except Exception as exc:
        logger.warning("get_info falhou: %s", exc)
        code, msg, params = _friendly_error(exc)
        return {"valid": False, "error": msg, "code": code, "params": params}


# ── Resolução via yt-dlp ─────────────────────────────────────────────────────

_YTDLP_ATTEMPTS  = 2     # tenta mais de uma vez — falha de rede transitória não deve virar reconexão cara
_YTDLP_RETRY_SEC = 1.5

_ANDROID_CLIENT = ["android"]


def _pick_stream_url(info: dict) -> Optional[str]:
    """Escolhe a URL de stream a partir do resultado do yt-dlp."""
    fmts = info.get("formats") or info.get("requested_formats") or []
    muxed = [f for f in fmts
             if f.get("vcodec") not in (None, "none")
             and f.get("acodec") not in (None, "none")
             and f.get("url")]
    if muxed:
        muxed.sort(key=lambda f: f.get("height") or 0, reverse=True)
        return muxed[0]["url"]
    for f in fmts:
        manifest = f.get("manifest_url")
        if manifest:
            return manifest
    direct = info.get("url")
    if direct:
        return direct
    if fmts and fmts[0].get("url"):
        return fmts[0]["url"]
    return None


def get_stream_url(url: str) -> str:
    """Resolve URL do YouTube para uma URL de stream reproduzível pelo MPV."""
    if _yt_dlp is None:
        raise RuntimeError("yt-dlp não instalado")
    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 10,
    }
    t0 = time.monotonic()

    try:
        android_opts = {**base_opts, "extractor_args": {"youtube": {"player_client": _ANDROID_CLIENT}}}
        with _yt_dlp.YoutubeDL(android_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        stream_url = _pick_stream_url(info)
        if stream_url:
            logger.info("[yt-dlp] URL selecionada (client android): %.80s  (%.2fs)",
                        stream_url, time.monotonic() - t0)
            return stream_url
    except Exception as exc:
        logger.warning("[yt-dlp] client android falhou (%s) — caindo pro client padrão", exc)

    last_exc: Optional[Exception] = None
    for attempt in range(1, _YTDLP_ATTEMPTS + 1):
        try:
            with _yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            stream_url = _pick_stream_url(info)
            if stream_url:
                logger.info("[yt-dlp] URL selecionada: %.80s  (%.2fs)",
                            stream_url, time.monotonic() - t0)
                return stream_url
            raise RuntimeError(f"yt-dlp não retornou URL de stream para: {url}")
        except Exception as exc:
            last_exc = exc
            if attempt < _YTDLP_ATTEMPTS:
                logger.warning("[yt-dlp] tentativa %d/%d falhou (%s) — retentando em %.1fs",
                                attempt, _YTDLP_ATTEMPTS, exc, _YTDLP_RETRY_SEC)
                time.sleep(_YTDLP_RETRY_SEC)
    raise last_exc
  