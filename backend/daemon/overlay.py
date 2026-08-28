"""Renderização e aplicação de overlays de logo no MPV via overlay-add BGRA.

O MPV exige pixels BGRA com alpha pré-multiplicado para overlay-add.
As dimensões replicam o CSS do player: max-height 14%, max-width 30%,
margens 4% horizontal e 5% vertical.
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mpv_daemon")

_MAX_H_PCT  = 0.14   # replica CSS: max-height 14%
_MAX_W_PCT  = 0.30   # replica CSS: max-width 30%
_MARGIN_X   = 0.04   # replica CSS: left/right 4%
_MARGIN_Y   = 0.05   # replica CSS: top/bottom 5%


def apply(mpv, logo_state: dict, logos_dir: Path) -> None:
    """Aplica todos os slots de logo ativos como overlay BGRA no MPV.

    Args:
        mpv:        instância python-mpv (pode ser None se MPV não inicializado)
        logo_state: {1: {"corner": str, "active": bool, "filename": str}, 2: {...}}
        logos_dir:  pasta backend/logos/
    """
    if not mpv:
        logger.warning("[overlay] MPV não disponível")
        return

    _remove_all(mpv)

    osd_w, osd_h = _osd_dimensions(mpv)
    logger.info("[overlay] dimensões OSD: %dx%d", osd_w, osd_h)

    max_w    = max(1, int(osd_w * _MAX_W_PCT))
    max_h    = max(1, int(osd_h * _MAX_H_PCT))
    margin_x = max(4, int(osd_w * _MARGIN_X))
    margin_y = max(4, int(osd_h * _MARGIN_Y))

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

        img = _load_and_resize(p, max_w, max_h)
        if img is None:
            continue
        w, h = img.size

        bgra_path = _write_bgra_tmp(img, slot)
        if bgra_path is None:
            continue

        x, y = _corner_pos(s["corner"], osd_w, osd_h, w, h, margin_x, margin_y)
        try:
            mpv.command(
                "overlay-add",
                str(slot), str(x), str(y),
                str(bgra_path), "0",
                "bgra",
                str(w), str(h), str(w * 4),
            )
            logger.info("[overlay] slot=%d OK pos=(%d,%d) %dx%d arquivo=%s",
                        slot, x, y, w, h, p.name)
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
        w = int(mpv.osd_width  or mpv.width  or 1920)
        h = int(mpv.osd_height or mpv.height or 1080)
        return w, h
    except Exception:
        return 1920, 1080


def _load_and_resize(path: Path, max_w: int, max_h: int):
    """Carrega imagem, converte para RGBA e redimensiona mantendo proporção.

    Retorna a imagem PIL (modo RGBA) redimensionada, ou None em caso de erro.
    """
    try:
        from PIL import Image
        img = Image.open(str(path)).convert("RGBA")
        w, h = img.size
        ratio = min(max_h / h, max_w / w)
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        logger.info("[overlay] %s → %dx%d", path.name, new_w, new_h)
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


def _corner_pos(
    corner: str,
    osd_w: int, osd_h: int,
    w: int, h: int,
    mx: int, my: int,
) -> tuple[int, int]:
    """Calcula (x, y) do canto top-left do logo para o corner solicitado."""
    if corner == "tl":
        return max(0, mx),            max(0, my)
    if corner == "tr":
        return max(0, osd_w - w - mx), max(0, my)
    if corner == "bl":
        return max(0, mx),            max(0, osd_h - h - my)
    # br (default)
    return max(0, osd_w - w - mx), max(0, osd_h - h - my)
    