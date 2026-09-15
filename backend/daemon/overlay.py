"""Renderização e aplicação de overlays de logo no MPV via overlay-add BGRA.

O MPV exige pixels BGRA com alpha pré-multiplicado para overlay-add.
A logo deve ser entregue como canvas 1920x1080 com transparência — o editor
posiciona e dimensiona o conteúdo. O PlayLine cola o canvas inteiro em (0,0).
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mpv_daemon")

_CANVAS_W = 1920
_CANVAS_H = 1080


def apply(mpv, logo_state: dict, logos_dir: Path) -> None:
    """Aplica todos os slots de logo ativos como overlay BGRA no MPV."""
    if not mpv:
        logger.warning("[overlay] MPV não disponível")
        return

    _remove_all(mpv)

    osd_w, osd_h = _osd_dimensions(mpv)
    logger.info("[overlay] dimensões OSD: %dx%d", osd_w, osd_h)

    any_active = False
    for slot in (1, 2):
        s = logo_state[slot]
        logger.info("[overlay] slot=%d active=%s filename=%r", slot, s["active"], s["filename"])

        if not s["active"] or not s["filename"]:
            continue

        p = logos_dir / s["filename"]
        if not p.is_file():
            logger.error("[overlay] slot=%d arquivo não encontrado: %s", slot, p)
            continue

        img = _load_for_osd(p, osd_w, osd_h)
        if img is None:
            continue
        w, h = img.size

        bgra_path = _write_bgra_tmp(img, slot)
        if bgra_path is None:
            continue

        try:
            mpv.command(
                "overlay-add",
                str(slot), "0", "0",
                str(bgra_path), "0",
                "bgra",
                str(w), str(h), str(w * 4),
            )
            logger.info("[overlay] slot=%d OK %dx%d arquivo=%s", slot, w, h, p.name)
            any_active = True
        except Exception as exc:
            logger.error("[overlay] overlay-add slot=%d FALHOU: %s", slot, exc)

    if not any_active:
        logger.info("[overlay] nenhum overlay aplicado")


# ── Helpers privados ──────────────────────────────────────────────────────────

def _remove_all(mpv) -> None:
    for slot in (1, 2):
        try:
            mpv.command("overlay-remove", str(slot))
        except Exception:
            pass


def _osd_dimensions(mpv) -> tuple[int, int]:
    try:
        w = int(mpv.osd_width  or mpv.width  or _CANVAS_W)
        h = int(mpv.osd_height or mpv.height or _CANVAS_H)
        return w, h
    except Exception:
        return _CANVAS_W, _CANVAS_H


def _load_for_osd(path: Path, osd_w: int, osd_h: int):
    """Carrega a logo no tamanho original do canvas.

    Escala proporcionalmente apenas quando o OSD difere do canvas 1920x1080
    (ex: janela de debug em modo sem monitor secundário).
    Retorna a imagem PIL (modo RGBA), ou None em caso de erro.
    """
    try:
        from PIL import Image
        img = Image.open(str(path)).convert("RGBA")
        src_w, src_h = img.size

        if src_w != osd_w or src_h != osd_h:
            ratio = min(osd_w / src_w, osd_h / src_h)
            new_w = max(1, int(src_w * ratio))
            new_h = max(1, int(src_h * ratio))
            img = img.resize((new_w, new_h), Image.LANCZOS)
            logger.info("[overlay] %s escalado %dx%d → %dx%d", path.name, src_w, src_h, new_w, new_h)
        else:
            logger.info("[overlay] %s %dx%d (tamanho original)", path.name, src_w, src_h)

        return img
    except Exception as exc:
        logger.error("[overlay] erro ao carregar %s: %s", path.name, exc)
        return None


def _write_bgra_tmp(img, slot: int) -> Optional[Path]:
    """Converte RGBA → BGRA pré-multiplicado e grava em arquivo temporário.

    Premultiplica e reordena os canais via PIL (ImageChops.multiply, em C) em
    vez de um loop Python por pixel — para uma logo típica isso troca dezenas
    de milhares de iterações Python por 3 operações vetorizadas, sensível
    sobretudo em CPUs mais fracas (é chamado toda vez que a logo é ativada
    ou trocada).
    """
    try:
        from PIL import Image, ImageChops
        r, g, b, a = img.split()
        r = ImageChops.multiply(r, a)
        g = ImageChops.multiply(g, a)
        b = ImageChops.multiply(b, a)
        bgra = Image.merge("RGBA", (b, g, r, a))
        tmp = Path(tempfile.gettempdir()) / f"playline_logo_{slot}.bgra"
        tmp.write_bytes(bgra.tobytes())
        return tmp
    except Exception as exc:
        logger.error("[overlay] erro ao gravar BGRA slot=%d: %s", slot, exc)
        return None
