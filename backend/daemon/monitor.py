"""Detecção de monitor secundário e posicionamento da janela MPV (Windows)."""

import logging
import time
from typing import Optional

logger = logging.getLogger("mpv_daemon")


def get_secondary_monitor_rect() -> Optional[tuple]:
    """Retorna (left, top, right, bottom) do monitor secundário, ou None."""
    try:
        import ctypes
        import ctypes.wintypes

        monitors = []

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.wintypes.RECT),
            ctypes.c_double,
        )

        def _cb(_hMon, _hdcMon, lprc, _data):
            r = lprc.contents
            monitors.append((r.left, r.top, r.right, r.bottom))
            return True

        ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)

        for left, top, right, bottom in monitors:
            if left != 0 or top != 0:
                return (left, top, right, bottom)

        if len(monitors) >= 2:
            return monitors[1]

    except Exception as exc:
        logger.warning("Não foi possível detectar monitor secundário: %s", exc)

    return None


def secondary_monitor_geometry() -> str:
    """Retorna a geometry MPV do monitor secundário no formato 'WxH+X+Y'.

    Exemplo: '1920x1080+1920+0'. Retorna string vazia se não houver secundário.
    Especificar W e H explicitamente é mais confiável que apenas '+X+Y' porque o
    MPV sabe exatamente onde e com que tamanho abrir sem depender da DPI.
    """
    rect = get_secondary_monitor_rect()
    if not rect:
        return ""
    left, top, right, bottom = rect
    return f"{right - left}x{bottom - top}+{left}+{top}"


def move_window_to_secondary(window_title: str) -> None:
    """Posiciona a janela identificada por window_title no monitor secundário.

    Usa SetWindowPos em vez de toggle de fullscreen para não invalidar o VO do
    MPV (fullscreen False→True em HDMI fecha a janela).
    """
    import ctypes

    rect = get_secondary_monitor_rect()
    if not rect:
        logger.info("Monitor secundário não encontrado — janela permanece no principal")
        return

    hwnd = None
    for _ in range(30):
        hwnd = ctypes.windll.user32.FindWindowW(None, window_title)
        if hwnd:
            break
        time.sleep(0.1)

    if not hwnd:
        logger.warning("Janela '%s' não encontrada para reposicionar", window_title)
        return

    left, top, right, bottom = rect
    width  = right - left
    height = bottom - top
    logger.info("Posicionando '%s' no monitor secundário: %dx%d+%d+%d",
                window_title, width, height, left, top)

    # HWND_TOPMOST=-1, SWP_NOACTIVATE=0x0010, SWP_SHOWWINDOW=0x0040
    ctypes.windll.user32.SetWindowPos(
        hwnd, ctypes.c_int(-1),
        left, top, width, height,
        0x0010 | 0x0040,
    )
