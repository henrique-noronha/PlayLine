"""Captura de frame do MPV para preview em tempo real no browser (fallback sem monitor secundário).

Usa screenshot-raw — lê o frame direto da memória do MPV (sem passar por
arquivo em disco). A imagem é escalada para _W px de largura e codificada
como JPEG para envio eficiente via WebSocket.
"""
import io
import logging
import time
from typing import Optional

logger = logging.getLogger("mpv_daemon")

_W = 720   # largura alvo do preview em pixels
_Q = 82    # qualidade JPEG (0-95)

_LAST_FAIL_LOG    = 0.0
_FAIL_LOG_INTERVAL = 10.0  # segundos mínimos entre logs de falha repetida


def capture_jpeg(mpv) -> Optional[bytes]:
    """Captura frame atual do MPV (com overlays) como JPEG.

    Retorna None se não há vídeo ativo ou se a captura falha.
    "window" inclui logos e overlay de texto sobrepostos pelo MPV.
    """
    global _LAST_FAIL_LOG
    if not mpv:
        return None
    try:
        from PIL import Image

        # Chama o comando raw diretamente em vez de mpv.screenshot_raw(): o wrapper
        # do python-mpv monta a imagem com largura = stride//4, ignorando a largura
        # real (w) — quando o driver alinha o stride (padding, comum em leitura de
        # textura D3D11), sobra uma faixa de bytes de lixo colada na borda direita.
        res = mpv.command("screenshot-raw", "window")
        if res["format"] != "bgr0":
            raise ValueError(f"formato de screenshot inesperado: {res['format']!r}")
        w, h, stride = res["w"], res["h"], res["stride"]
        img = Image.frombytes("RGBA", (stride // 4, h), res["data"])
        if stride // 4 != w:
            img = img.crop((0, 0, w, h))   # remove o padding do stride
        b, g, r, _a = img.split()
        img = Image.merge("RGB", (r, g, b))
        # Descarta frames de janela minimizada (dimensões inválidas)
        if img.width < 100 or img.height < 50:
            return None
        # Força sempre saída 16:9 para não quebrar proporção no canvas
        _H = round(_W * 9 / 16)
        img = img.resize((_W, _H), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=_Q, optimize=False)
        return buf.getvalue()

    except Exception as exc:
        now = time.monotonic()
        if now - _LAST_FAIL_LOG > _FAIL_LOG_INTERVAL:
            logger.warning("[preview] captura via MPV falhando: %s", exc)
            _LAST_FAIL_LOG = now
        return None
