"""Ponto de entrada do daemon MPV — lançado como processo independente por player.py.

"""

import asyncio
import logging

from daemon import MPVDaemon

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [mpv-daemon] %(levelname)s: %(message)s",
)

if __name__ == "__main__":
    d = MPVDaemon()
    try:
        asyncio.run(d.serve())
    except KeyboardInterrupt:
        logging.getLogger("mpv_daemon").info("Daemon encerrado")
