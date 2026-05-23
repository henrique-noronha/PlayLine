"""
Playlist Engine — gerencia a fila de reprodução e responde a eventos do Player.
"""

import json
import logging
import asyncio
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# schedule.json fica em backend/, um nível acima deste arquivo
SCHEDULE_PATH = Path(__file__).parent.parent / "schedule.json"


class PlaylistEngine:
    def __init__(self, player, broadcast: Callable):
        """
        player:    instância de Player
        broadcast: coroutine async que envia dicionário a todos os WS clients
        """
        self._player = player
        self._broadcast = broadcast
        self._items: list[dict] = []
        self._index: int = -1
        self._running: bool = False
        self._paused: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------ #
    # Roteiro                                                              #
    # ------------------------------------------------------------------ #

    def load_schedule(self) -> list[dict]:
        try:
            self._items = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
            logger.info("Roteiro carregado: %d itens", len(self._items))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.error("Falha ao carregar roteiro: %s", exc)
            self._items = []
        return self._items

    def save_schedule(self, items: list[dict]):
        self._items = items
        SCHEDULE_PATH.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Roteiro salvo: %d itens", len(items))

    def get_schedule(self) -> list[dict]:
        return self._items

    # ------------------------------------------------------------------ #
    # Controle de reprodução                                               #
    # ------------------------------------------------------------------ #

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def on_end_file(self, reason: str):
        """Chamado pelo Player (thread do MPV) quando um arquivo termina."""
        if reason in ("stop",):
            return
        if reason == "error":
            logger.warning("Arquivo com erro — avançando automaticamente")
        if self._running:
            if self._loop:
                asyncio.run_coroutine_threadsafe(self._advance(), self._loop)

    async def _advance(self):
        if self._index + 1 < len(self._items):
            await self.play_index(self._index + 1)
        else:
            self._running = False
            self._index = -1
            await self._broadcast({"event": "playlist_end"})
            logger.info("Fim da playlist")

    async def play(self):
        """Inicia a partir do item atual (ou do início)."""
        start = max(self._index, 0)
        await self.play_index(start)

    async def play_index(self, index: int):
        if not (0 <= index < len(self._items)):
            return
        self._index = index
        self._running = True
        self._paused = False
        item = self._items[index]
        await self._broadcast(
            {"event": "now_playing", "index": index, "item": item}
        )

    async def pause_toggle(self):
        self._paused = not self._paused
        if self._paused:
            await self._broadcast({"event": "paused"})
        else:
            await self._broadcast({"event": "resumed"})

    async def stop(self):
        self._running = False
        self._paused = False
        await self._broadcast({"event": "stopped"})

    async def next_item(self):
        await self._advance()

    async def prev_item(self):
        target = max(self._index - 1, 0)
        await self.play_index(target)

    async def jump_to(self, index: int):
        await self.play_index(index)

    # ------------------------------------------------------------------ #
    # Estado                                                               #
    # ------------------------------------------------------------------ #

    def state(self) -> dict:
        item = self._items[self._index] if 0 <= self._index < len(self._items) else None
        return {
            "event": "state",
            "running": self._running,
            "paused": self._paused,
            "index": self._index,
            "current_item": item,
            "total_items": len(self._items),
        }
