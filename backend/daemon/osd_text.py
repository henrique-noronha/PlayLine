"""Overlay de texto (hora + temperatura + cidade) via overlay-add BGRA.

"""

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mpv_daemon")

_SLOT     = "3"
_MARGIN_X = 0.04
_MARGIN_Y = 0.07

_BG_TIME  = (68,  68,  68, 190)    # cinza — hora
_BG_TEMP  = (52,  52,  52, 190)    # cinza — temp
_BG_CITY  = (38,  38,  38, 190)    # cinza — cidade
_FG_LIGHT = (255, 255, 255, 255)   # branco — hora, temp e cidade


def apply(mpv, config: dict, temperature: Optional[str]) -> None:
    if not mpv:
        return

    if not config.get("active"):
        _remove(mpv)
        return

    show_time = config.get("show_time", True)
    show_temp = config.get("show_temp", True)

    if not show_time and not show_temp:
        _remove(mpv)
        return

    corner    = config.get("corner", "tl")
    osd_w, osd_h = _osd_dims(mpv)
    font_sz   = max(8, int(osd_h * 0.028))
    margin_x  = max(4, int(osd_w * _MARGIN_X))
    margin_y  = max(6, int(osd_h * _MARGIN_Y))

    result = _render(config, temperature, font_sz)
    if result is None:
        return

    bgra_bytes, w, h = result
    x, y = _corner_pos(corner, osd_w, osd_h, w, h, margin_x, margin_y)
    logger.debug("[osd_text] osd=%dx%d font=%d bmp=%dx%d pos=(%d,%d) margin_y=%d",
                 osd_w, osd_h, font_sz, w, h, x, y, margin_y)
    try:
        import tempfile, datetime
        dbg = Path(tempfile.gettempdir()) / "playline_osd_debug.txt"
        line = (f"{datetime.datetime.now():%H:%M:%S} "
                f"osd={osd_w}x{osd_h} font={font_sz} "
                f"bmp={w}x{h} pos=({x},{y}) margin_y={margin_y}\n")
        with open(dbg, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

    tmp = Path(tempfile.gettempdir()) / "playline_text.bgra"
    try:
        tmp.write_bytes(bgra_bytes)
    except Exception as exc:
        logger.error("[osd_text] erro ao escrever bgra: %s", exc)
        return

    try:
        mpv.command(
            "overlay-add",
            _SLOT, str(x), str(y),
            str(tmp), "0",
            "bgra",
            str(w), str(h), str(w * 4),
        )
    except Exception as exc:
        logger.warning("[osd_text] overlay-add falhou: %s", exc)


def remove(mpv) -> None:
    _remove(mpv)


def _remove(mpv) -> None:
    try:
        mpv.command("overlay-remove", _SLOT)
    except Exception:
        pass


# ── Helpers ──────────────────────────────────────────────────────────────────

def _osd_dims(mpv) -> tuple[int, int]:
    try:
        w = int(mpv.osd_width  or mpv.width  or 1920)
        h = int(mpv.osd_height or mpv.height or 1080)
        return w, h
    except Exception:
        return 1920, 1080


def _load_font(size: int):
    from PIL import ImageFont
    for name in ("segoeuib.ttf", "segoeui.ttf", "arial.ttf", "verdana.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _render(config: dict, temperature: Optional[str], font_sz: int) -> Optional[tuple]:
    try:
        from PIL import Image, ImageDraw, ImageChops

        show_time = config.get("show_time", True)
        show_temp = config.get("show_temp", True)
        city      = ((config.get("city") or "Palmas").split(",")[0]).strip() or "Palmas"

        time_str = datetime.now().strftime("%H:%M:%S") if show_time else None
        temp_str = temperature if (show_temp and temperature) else None

        if not time_str and not temp_str:
            return None

        font_main = _load_font(font_sz)
        font_city = _load_font(max(4, int(font_sz * 0.72)))

        pad_x  = max(4, int(font_sz * 0.40))
        pad_y  = max(3, int(font_sz * 0.28))
        pad_cy = max(3, int(font_sz * 0.30))

        probe = Image.new("RGBA", (1, 1))
        d     = ImageDraw.Draw(probe)

        def measure(txt, fnt):
            bb = d.textbbox((0, 0), txt, font=fnt)
            return bb[2] - bb[0], bb[3] - bb[1]

        def cpos(txt, fnt, box_x, box_y, box_w, box_h):
            """Posição (x,y) para centralizar visualmente o texto no retângulo."""
            bb = d.textbbox((0, 0), txt, font=fnt)
            x = box_x + (box_w - (bb[2] - bb[0])) // 2 - bb[0]
            y = box_y + (box_h - (bb[3] - bb[1])) // 2 - bb[1]
            return x, y

        tw, th = measure(time_str, font_main) if time_str else (0, 0)
        ew, eh = measure(temp_str, font_main) if temp_str else (0, 0)
        cw, ch = measure(city,     font_city)

        both      = bool(time_str and temp_str)
        top_h     = max(th if time_str else 0, eh if temp_str else 0) + pad_y * 2
        city_h    = ch + pad_cy * 2

        if both:
            left_w  = tw + pad_x * 2   # hora  (esquerda)
            right_w = ew + pad_x * 2   # temp  (direita)
            top_w   = left_w + right_w
        else:
            sw, _   = (tw, th) if time_str else (ew, eh)
            top_w   = sw + pad_x * 2
            left_w  = top_w

        total_w = max(top_w, cw + pad_x * 2, 50)
        total_h = top_h + city_h

        img  = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Linha superior
        if both:
            # Hora à esquerda (azul)
            draw.rectangle([0, 0, left_w - 1, top_h - 1], fill=_BG_TIME)
            draw.text(cpos(time_str, font_main, 0, 0, left_w, top_h), time_str, font=font_main, fill=_FG_LIGHT)
            # Temp à direita (amarelo) — ocupa o restante
            r_start = left_w
            r_w     = total_w - r_start
            draw.rectangle([r_start, 0, total_w - 1, top_h - 1], fill=_BG_TEMP)
            draw.text(cpos(temp_str, font_main, r_start, 0, r_w, top_h), temp_str, font=font_main, fill=_FG_LIGHT)
        elif time_str:
            draw.rectangle([0, 0, total_w - 1, top_h - 1], fill=_BG_TIME)
            draw.text(cpos(time_str, font_main, 0, 0, total_w, top_h), time_str, font=font_main, fill=_FG_LIGHT)
        else:
            draw.rectangle([0, 0, total_w - 1, top_h - 1], fill=_BG_TEMP)
            draw.text(cpos(temp_str, font_main, 0, 0, total_w, top_h), temp_str, font=font_main, fill=_FG_LIGHT)

        # Cidade em baixo (verde)
        draw.rectangle([0, top_h, total_w - 1, total_h - 1], fill=_BG_CITY)
        draw.text(cpos(city, font_city, 0, top_h, total_w, city_h), city, font=font_city, fill=_FG_LIGHT)

        # RGBA → BGRA pré-multiplicado (vetorizado via PIL, ver overlay.py —
        # troca um loop Python por pixel por 3 operações ImageChops em C,
        # ~24x mais rápido, sensível sobretudo em CPUs mais fracas já que
        # roda a cada segundo enquanto a hora/temp estiver ativa)
        r, g, b, a = img.split()
        r = ImageChops.multiply(r, a)
        g = ImageChops.multiply(g, a)
        b = ImageChops.multiply(b, a)
        bgra_img = Image.merge("RGBA", (b, g, r, a))

        return bgra_img.tobytes(), total_w, total_h

    except Exception as exc:
        logger.error("[osd_text] erro ao renderizar: %s", exc)
        return None


def _corner_pos(corner, osd_w, osd_h, w, h, mx, my) -> tuple[int, int]:
    if corner == "tl": return max(0, mx),             max(0, my)
    if corner == "tr": return max(0, osd_w - w - mx), max(0, my)
    if corner == "bl": return max(0, mx),             max(0, osd_h - h - my)
    return max(0, osd_w - w - mx), max(0, osd_h - h - my)
