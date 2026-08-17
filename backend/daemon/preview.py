"""Captura de frame do MPV para preview em tempo real no browser.

Usa screenshot-to-file com modo "window" — captura a janela MPV incluindo
OSD (logos e overlay de texto). A imagem é escalada para _W px de largura
e codificada como JPEG para envio eficiente via WebSocket.
"""
import io
import logging
import tempfile
import time
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

        # Remove arquivo anterior para garantir que PIL lê o frame recém-capturado
        # (evita race condition com cache de escrita do SO no Windows)
        try:
            if _TMP.exists():
                _TMP.unlink()
        except OSError:
            pass

        # "window" = captura o conteúdo renderizado da janela MPV (com OSD/overlays)
        mpv.command("screenshot-to-file", str(_TMP), "window")

        # Aguarda o arquivo ser escrito (até 300ms) — necessário no Windows onde o
        # write pode estar em cache quando python-mpv retorna do command()
        for _ in range(30):
            if _TMP.is_file() and _TMP.stat().st_size > 0:
                break
            time.sleep(0.01)
        else:
            return None

        with Image.open(str(_TMP)) as img:
            img = img.convert("RGB")
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
        logger.debug("[preview] captura falhou: %s", exc)
        return None
