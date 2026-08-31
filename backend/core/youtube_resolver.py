"""Resolução de streams do YouTube.

Resolve a URL do vídeo/live pra uma URL HLS direta via yt-dlp, pra o MPV
tocar sem precisar baixar o arquivo inteiro.
"""

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

_YT_ERROR_MAP = [
    (re.compile(r"live event will begin in (\d+) hour",  re.I), lambda m: f"Esta live começa em {m.group(1)} hora{'s' if int(m.group(1)) != 1 else ''}"),
    (re.compile(r"live event will begin in (\d+) minute", re.I), lambda m: f"Esta live começa em {m.group(1)} minuto{'s' if int(m.group(1)) != 1 else ''}"),
    (re.compile(r"live event will begin in (\d+) day",   re.I), lambda m: f"Esta live começa em {m.group(1)} dia{'s' if int(m.group(1)) != 1 else ''}"),
    (re.compile(r"private video",                        re.I), lambda m: "Vídeo privado"),
    (re.compile(r"video unavailable",                    re.I), lambda m: "Vídeo indisponível"),
    (re.compile(r"members.only",                         re.I), lambda m: "Conteúdo exclusivo para membros"),
    (re.compile(r"confirm your age",                     re.I), lambda m: "Restrição de idade"),
    (re.compile(r"copyright",                            re.I), lambda m: "Conteúdo bloqueado por direitos autorais"),
]

def _friendly_error(exc: Exception) -> str:
    raw = _ANSI_RE.sub("", str(exc))
    for pattern, msg_fn in _YT_ERROR_MAP:
        m = pattern.search(raw)
        if m:
            return msg_fn(m)
    # Remove prefixo "ERROR: [youtube] ID: " deixando só a mensagem
    clean = re.sub(r"^ERROR:\s*\[youtube\]\s*[A-Za-z0-9_-]+:\s*", "", raw).strip()
    return clean or "Não foi possível obter informações do vídeo"


def get_info(url: str) -> dict:
    """Retorna metadados básicos sem baixar o stream."""
    if _yt_dlp is None:
        return {"valid": False, "error": "yt-dlp não instalado"}
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
        return {"valid": False, "error": _friendly_error(exc)}


# ── Resolução via yt-dlp ─────────────────────────────────────────────────────

_YTDLP_ATTEMPTS  = 2     # tenta mais de uma vez — falha de rede transitória não deve virar reconexão cara
_YTDLP_RETRY_SEC = 1.5

# O client "android" ainda serve HLS com vídeo+áudio já combinados num único
# formato — o MPV abre um stream só e começa a decodificar. Os clients
# padrão (mweb/web/tv/visionos) só servem formatos separados (vídeo-only +
# áudio-only): aí a única opção é o manifesto HLS mestre, que lista ~8
# variantes e o MPV enumera todas antes de tocar (10s+ só nisso). Por ser um
# client específico visado pelas restrições do YouTube, uma falha aqui não é
# retentada — cai direto pro fallback abaixo.
_ANDROID_CLIENT = ["android"]


def _pick_stream_url(info: dict) -> Optional[str]:
    """Escolhe a URL de stream a partir do resultado do yt-dlp.

    Prioridade: formato já muxado (vídeo+áudio juntos, quando o client
    usado ainda oferece um) > manifesto HLS mestre (o MPV escolhe a
    variante e a trilha de áudio sozinho) > URL direta > primeiro formato
    disponível.
    """
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
