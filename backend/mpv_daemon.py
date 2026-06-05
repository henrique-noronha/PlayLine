"""Ponto de entrada do daemon MPV — lançado como processo independente por player.py.

A lógica está em backend/daemon/:
    daemon.py    — MPVDaemon (orquestração, servidor TCP, comandos)
    overlay.py   — renderização de logo BGRA via overlay-add
    monitor.py   — detecção de monitor secundário e posicionamento
    checkpoint.py — leitura/escrita do checkpoint de posição
    protocol.py  — parsing do evento end-file do MPV
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
