"""Resolução de streams do YouTube.

Estratégia: InnerTube API (TVHTML5 client) em ~300 ms como caminho rápido;
yt-dlp como fallback caso o InnerTube falhe ou retorne sem URL HLS.
"""

import json
import logging
import re
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_YT_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch|live)|youtu\.be/)"
)

_VIDEO_ID_RE = re.compile(
    r"[?&]v=([A-Za-z0-9_-]{11})"
    r"|youtu\.be/([A-Za-z0-9_-]{11})"
    r"|youtube\.com/live/([A-Za-z0-9_-]{11})"
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


# ── Caminho rápido: InnerTube API ────────────────────────────────────────────

def _extract_video_id(url: str) -> "str | None":
    m = _VIDEO_ID_RE.search(url)
    return (m.group(1) or m.group(2) or m.group(3)) if m else None


def _innertube_hls(video_id: str) -> "str | None":
    """POST para a API InnerTube — tenta ANDROID e IOS em sequência, retorna m3u8."""
    clients = [
        {
            "name": "ANDROID",
            "num": "3",
            "version": "19.29.37",
            "context": {
                "clientName": "ANDROID",
                "clientVersion": "19.29.37",
                "androidSdkVersion": 30,
                "hl": "pt",
                "gl": "BR",
            },
            "ua": "com.google.android.youtube/19.29.37 (Linux; U; Android 11) gzip",
        },
        {
            "name": "IOS",
            "num": "5",
            "version": "19.29.1",
            "context": {
                "clientName": "IOS",
                "clientVersion": "19.29.1",
                "deviceMake": "Apple",
                "deviceModel": "iPhone16,2",
                "osName": "iPhone",
                "osVersion": "17.5.1.21F90",
                "hl": "pt",
                "gl": "BR",
            },
            "ua": "com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)",
        },
    ]

    for client in clients:
        body = json.dumps({
            "videoId": video_id,
            "context": {"client": client["context"]},
        }).encode()
        req = urllib.request.Request(
            "https://www.youtube.com/youtubei/v1/player?prettyPrint=false",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-YouTube-Client-Name": client["num"],
                "X-YouTube-Client-Version": client["version"],
                "User-Agent": client["ua"],
                "Origin": "https://www.youtube.com",
                "Referer": "https://www.youtube.com/",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            logger.warning("InnerTube [%s] erro de rede: %s", client["name"], exc)
            continue

        status = data.get("playabilityStatus", {}).get("status")
        if status != "OK":
            reason = data.get("playabilityStatus", {}).get("reason", "")
            logger.warning("InnerTube [%s] status=%s (%s)", client["name"], status, reason)
            continue

        hls = data.get("streamingData", {}).get("hlsManifestUrl")
        if hls:
            logger.info("InnerTube [%s] OK — HLS obtido", client["name"])
            return hls

        logger.warning("InnerTube [%s] OK mas sem hlsManifestUrl", client["name"])

    return None


# ── Fallback: yt-dlp completo ────────────────────────────────────────────────

def _ytdlp_stream_url(url: str) -> str:
    if _yt_dlp is None:
        raise RuntimeError("yt-dlp não instalado")
    # player_client=mweb resolve melhor lives do YouTube — retorna manifests HLS
    # estáveis sem os problemas de rate-limit e expiração do cliente padrão.
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[protocol=m3u8_native]/best[protocol=m3u8]/best",
        "extractor_args": {"youtube": {"player_client": ["mweb"]}},
    }
    with _yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    direct = info.get("url")
    if direct:
        proto = info.get("protocol", "")
        logger.info("[yt-dlp] protocolo selecionado: %s  url: %.80s", proto, direct)
        return direct
    fmts = info.get("requested_formats") or []
    if fmts and fmts[0].get("url"):
        proto = fmts[0].get("protocol", "")
        logger.info("[yt-dlp] protocolo selecionado (fmt[0]): %s  url: %.80s", proto, fmts[0]["url"])
        return fmts[0]["url"]
    raise RuntimeError(f"yt-dlp não retornou URL de stream para: {url}")


# ── API pública ──────────────────────────────────────────────────────────────

def get_stream_url(url: str) -> str:
    """Resolve URL do YouTube para URL HLS direta.

    Tenta InnerTube (~300 ms) antes de yt-dlp (~3 s).
    """
    import time
    t0 = time.monotonic()

    video_id = _extract_video_id(url)
    logger.info("[DIAGNÓSTICO] Iniciando resolução — video_id=%s url=%s", video_id, url)

    if video_id:
        try:
            t1 = time.monotonic()
            hls = _innertube_hls(video_id)
            t_innertube = time.monotonic() - t1
            if hls:
                logger.info("[DIAGNÓSTICO] InnerTube OK em %.2fs — HLS obtido", t_innertube)
                return hls
            else:
                logger.warning("[DIAGNÓSTICO] InnerTube retornou None em %.2fs — caindo no yt-dlp", t_innertube)
        except Exception as exc:
            logger.warning("[DIAGNÓSTICO] InnerTube ERRO em %.2fs: %s — caindo no yt-dlp",
                           time.monotonic() - t0, exc)
    else:
        logger.warning("[DIAGNÓSTICO] video_id não extraído da URL — indo direto ao yt-dlp")

    t2 = time.monotonic()
    result = _ytdlp_stream_url(url)
    logger.info("[DIAGNÓSTICO] yt-dlp concluído em %.2fs", time.monotonic() - t2)
    return result
