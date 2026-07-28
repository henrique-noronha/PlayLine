"""Ponto de entrada do daemon MPV — lançado como processo independente por player.py.

"""

import asyncio
import logging
import sys
from pathlib import Path

_LOG_PATH = (
    Path(sys.executable).parent / "daemon.log"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "daemon.log"
)

_handler_file = logging.FileHandler(_LOG_PATH, encoding="utf-8")
_handler_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [mpv-daemon] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(), _handler_file],
)

from daemon import MPVDaemon  # noqa: E402

if __name__ == "__main__":
    logging.getLogger("mpv_daemon").info("Daemon iniciado — log em: %s", _LOG_PATH)
    d = MPVDaemon()
    try:
        asyncio.run(d.serve())
    except KeyboardInterrupt:
        logging.getLogger("mpv_daemon").info("Daemon encerrado")
