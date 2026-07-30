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


def send_window_to_back(window_title: str) -> None:
    """Envia a janela para HWND_BOTTOM (atrás de todas as outras).

    Filtra por PID do processo atual para evitar ambiguidade quando PyWebView e MPV
    compartilham o mesmo título "PlayLine" — apenas a janela MPV pertence ao daemon.
    """
    import ctypes
    import ctypes.wintypes

    current_pid = ctypes.windll.kernel32.GetCurrentProcessId()
    found_hwnd = None

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        nonlocal found_hwnd
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != current_pid:
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value == window_title:
            found_hwnd = hwnd
            return False
        return True

    for _ in range(30):
        found_hwnd = None
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
        if found_hwnd:
            break
        time.sleep(0.1)

    if not found_hwnd:
        logger.warning("Janela '%s' não encontrada no processo atual", window_title)
        return

    # HWND_BOTTOM=1, SWP_NOSIZE=0x0001, SWP_NOMOVE=0x0002, SWP_NOACTIVATE=0x0010
    ctypes.windll.user32.SetWindowPos(
        found_hwnd, ctypes.c_int(1),
        0, 0, 0, 0,
        0x0001 | 0x0002 | 0x0010,
    )
    logger.info("Janela '%s' enviada para o fundo (HWND_BOTTOM)", window_title)
