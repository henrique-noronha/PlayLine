"""Captura de frame do MPV para preview em tempo real no browser.

Usa screenshot-to-file com modo "window" — captura a janela MPV incluindo
OSD (logos e overlay de texto). A imagem é escalada para _W px de largura
e codificada como JPEG para envio eficiente via WebSocket.
"""
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mpv_daemon")

_W   = 720   # largura alvo do preview em pixels
_Q   = 82    # qualidade JPEG (0-95)
_TMP = Path(tempfile.gettempdir()) / "playline_preview.jpg"


def capture_jpeg(mpv) -> Optional[bytes]:
    """Captura frame atual do MPV (com overlays) como JPEG.

    Retorna None se não há vídeo ativo ou se a captura falha.
    A captura usa modo 'window': inclui logos e overlay de texto sobrepostos pelo MPV.
    """
    if not mpv:
        return None
    try:
        from PIL import Image

        # "window" = captura o conteúdo renderizado da janela MPV (com OSD/overlays)
        mpv.command("screenshot-to-file", str(_TMP), "window")

        if not _TMP.is_file() or _TMP.stat().st_size == 0:
            return None

        with Image.open(str(_TMP)) as img:
            img = img.convert("RGB")
            if img.width > 0 and img.width != _W:
                new_h = max(1, int(img.height * _W / img.width))
                img = img.resize((_W, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=_Q, optimize=False)
            return buf.getvalue()

    except Exception as exc:
        logger.debug("[preview] captura falhou: %s", exc)
        return None
