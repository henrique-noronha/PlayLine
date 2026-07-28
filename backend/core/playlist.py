"""
Playlist Engine — gerencia a fila de reprodução e responde a eventos do Player.
"""

import json
import logging
import asyncio
import sys
from pathlib import Path
from typing import Callable, Optional

from .history import HistoryManager

logger = logging.getLogger(__name__)

_DATA_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent.parent
SCHEDULE_PATH   = _DATA_DIR / "schedule.json"
CHECKPOINT_PATH = _DATA_DIR / "checkpoint.json"


class PlaylistEngine:
    def __init__(self, player, broadcast: Callable):
        self._player = player
        self._broadcast = broadcast
        self._items: list[dict] = []
        self._index: int = -1
        self._running: bool = False
        self._paused: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._advance_seq: int = 0  # incrementado a cada avanço; evita avanço duplo
        self._skip_end_file: int = 0  # end-files a ignorar após substituição manual de vídeo
        self._preloading: bool = False  # True quando próximo vídeo já está na fila do MPV
        self._history = HistoryManager()

    # Roteiro                                                              #
 
    def load_schedule(self) -> list[dict]:
        try:
            self._items = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
            logger.info("Roteiro carregado: %d itens", len(self._items))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.error("Falha ao carregar roteiro: %s", exc)
            self._items = []
        self._maybe_prefetch_yt()
        return self._items

    def save_schedule(self, items: list[dict], from_ui: bool = False):
        if from_ui:
            current_id  = self._items[0].get("id") if self._items else None
            new_first_id = items[0].get("id") if items else None
            if current_id != new_first_id:
                # O primeiro item mudou: invalida qualquer _advance pendente
                # e para o avanço automático para não consumir o novo roteiro.
                self._advance_seq += 1
                self._running     = False
                self._preloading  = False
                logger.debug("Roteiro substituído via UI — avanço automático pausado")
            elif self._preloading:
                old_next_id = self._items[1].get("id") if len(self._items) > 1 else None
                new_next_id = items[1].get("id") if len(items) > 1 else None
                if old_next_id != new_next_id:
                    self._preloading = False
                    logger.debug("Pré-carregamento cancelado — próximo item alterado externamente")
        self._items = items
        SCHEDULE_PATH.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Roteiro salvo: %d itens", len(items))
        self._maybe_prefetch_yt()

    def get_schedule(self) -> list[dict]:
        return self._items

    def _maybe_prefetch_yt(self):
        """Pré-resolve todas as URLs YouTube live do roteiro.
        O daemon deduplica: ignora URLs já em cache ou com resolução em andamento.
        """
        for item in self._items:
            if item.get("live") and item.get("path"):
                self._player.prefetch_yt(item["path"])
                logger.debug("Prefetch YouTube: %s", item["path"])

    def _read_checkpoint(self) -> Optional[dict]:
        try:
            return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None

    # Recuperação após crash                                               #

    def restore_after_crash(self):
        """
        Detecta se o daemon já está reproduzindo algo após um crash/reinício
        do servidor. Deve ser chamado via run_in_executor (é bloqueante).
        """
        playing = self._player.get_playing_path()
        if playing is None:
            logger.info("Daemon ocioso — aguardando comando de play")
            return

        logger.info("Daemon em reprodução: %s — retomando estado", playing)
        self._running = True

        # Localiza o item em reprodução no roteiro para definir o índice correto
        idx = next(
            (i for i, it in enumerate(self._items) if it.get("path") == playing),
            0,
        )
        self._index = idx
        if idx > 0:
            logger.info("Retomando no índice %d do roteiro: %s", idx, playing)

        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(self.state()), self._loop
            )

    # Controle de reprodução                                               #

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def on_end_file(self, reason: str):
        """Chamado pelo Player (thread de leitura TCP) quando um arquivo termina."""
        if reason == "stop":
            # end-file(stop) vem de loadfile replace ou do comando stop — não avança
            if self._skip_end_file > 0:
                self._skip_end_file -= 1
            return
        if reason == "mpv_closed":
            self._preloading = False
            if self._loop:
                asyncio.run_coroutine_threadsafe(self._on_mpv_closed(), self._loop)
            return
        if reason == "error":
            self._preloading = False  # erro: não confia no estado da playlist interna
            self._history.close_entry("error")
            logger.warning("Arquivo com erro — avançando automaticamente")
        elif reason == "eof":
            self._history.close_entry("completed")
        if self._skip_end_file > 0:
            self._skip_end_file -= 1
            logger.debug("end-file ignorado (substituição por avanço manual)")
            return
        if self._running:
            if self._loop:
                seq = self._advance_seq
                asyncio.run_coroutine_threadsafe(
                    self._advance(expected_seq=seq), self._loop
                )

    async def _on_mpv_closed(self):
        self._advance_seq += 1  # invalida qualquer avanço pendente
        self._running = False
        self._paused = False
        self._index = -1
        self._preloading = False
        self._history.close_entry("interrupted")
        await self._broadcast({"event": "mpv_closed"})
        await self._broadcast({"event": "stopped"})
        logger.info("Playout parado (janela MPV fechada)")

    async def _advance(self, expected_seq: int = -1):
        """
        Consome o clipe atual e avança para o próximo.
        expected_seq >= 0: ignora se outro avanço já ocorreu (evita avanço duplo
        quando end-file natural e next/jump chegam simultaneamente).
        expected_seq = -1: avança incondicionalmente (next manual, jump).
        """
        if expected_seq >= 0 and expected_seq != self._advance_seq:
            logger.debug("_advance obsoleto (seq %d != %d) — ignorado", expected_seq, self._advance_seq)
            return
        self._advance_seq += 1

        if self._items:
            self._items.pop(0)
            self.save_schedule(self._items)

        # Pula itens sem caminho válido
        while self._items and not self._items[0].get("path"):
            logger.warning("Pulando item sem caminho: %s", self._items[0].get("title", "?"))
            self._items.pop(0)
            self.save_schedule(self._items)

        await self._broadcast({"event": "schedule_updated", "items": list(self._items)})

        if self._items:
            if expected_seq < 0:  # avanço manual — cancela preload e substitui explicitamente
                self._preloading = False
                self._skip_end_file += 1
            await self.play_index(0)
        else:
            self._running = False
            self._index = -1
            await self._broadcast({"event": "playlist_end"})
            logger.info("Fim da playlist")

    async def play(self):
        """Inicia pelo primeiro item do roteiro."""
        self._advance_seq += 1  # invalida qualquer end-file pendente
        await self.play_index(0)

    async def play_index(self, index: int):
        if not (0 <= index < len(self._items)):
            return
        self._index = index
        self._running = True
        self._paused = False
        item = self._items[index]

        if item.get("path"):
            self._history.open_entry(item.get("title") or item["path"].split("\\")[-1], item["path"])
            if self._preloading:
                # MPV já avançou para este vídeo via playlist interna (pré-carregado)
                # Não chama player.play() para não interromper a reprodução
                logger.info("MPV já está em transição para: %s", item["path"])
            else:
                self._player.play(
                    item["path"],
                    start_time=item.get("start_time"),
                    end_time=item.get("end_time"),
                )

            self._preloading = False

            # Pré-carrega o próximo vídeo na fila do MPV para transição sem flash.
            # Live streams e clipes com corte não são pré-carregados.
            # A URL YouTube é pré-resolvida em background para eliminar o delay do yt-dlp.
            if index + 1 < len(self._items):
                next_item = self._items[index + 1]
                item_has_trim = item.get("start_time") or item.get("end_time")
                next_has_trim = next_item.get("start_time") or next_item.get("end_time")
                if (not item.get("live") and next_item.get("path")
                        and not next_item.get("live")
                        and not item_has_trim and not next_has_trim):
                    self._player.preload(next_item["path"])
                    self._preloading = True
                elif next_item.get("live") and next_item.get("path"):
                    # Prefetch para qualquer → live (cobre regular→live e live→live)
                    self._player.prefetch_yt(next_item["path"])

            # Retoma posição do checkpoint se for a primeira reprodução após reinício.
            # Pula se o clipe tem start_time explícito (posição já definida pelo trim).
            cp = self._read_checkpoint()
            if cp and cp.get("path") == item["path"] and not item.get("start_time"):
                pos = cp.get("position", 0.0)
                if pos > 2.0:
                    asyncio.ensure_future(self._deferred_seek(pos, item["path"]))

        await self._broadcast(
            {"event": "now_playing", "index": index, "item": item}
        )

    async def _deferred_seek(self, position: float, expected_path: str):
        """Aguarda o MPV carregar o arquivo e então busca a posição salva.
        Cancela o seek se o item atual mudou antes dos 1.5s."""
        await asyncio.sleep(1.5)
        current_path = self._items[0].get("path") if self._items else None
        if current_path != expected_path:
            logger.debug("_deferred_seek cancelado — item mudou antes do seek")
            return
        self._player.seek(position)
        logger.info("Retomando posição: %.1f s", position)

    async def pause_toggle(self):
        self._paused = not self._paused
        if self._paused:
            self._history.mark_pause()
            self._player.pause()
            await self._broadcast({"event": "paused"})
        else:
            self._player.resume()
            await self._broadcast({"event": "resumed"})

    async def stop(self):
        self._advance_seq += 1  # invalida qualquer end-file pendente
        self._running = False
        self._paused = False
        self._index = -1
        self._preloading = False
        self._history.close_entry("stopped")
        self._player.stop()
        await self._broadcast({"event": "stopped"})

    async def next_item(self):
        self._history.close_entry("skipped")
        await self._advance()

    def set_volume(self, volume: int):
        self._player.set_volume(volume)

    def set_logo(self, slot: int, filename: str, corner: str, active: bool):
        self._player.set_logo(slot, filename, corner, active)

    def request_logo_list(self):
        self._player.request_logo_list()

    def set_text_overlay(self, config: dict):
        self._player.set_text_overlay(config)

    def request_text_overlay_state(self):
        self._player.get_text_overlay()

    async def prev_item(self):
        pass  # roteiro linear — não retrocede

    async def jump_to(self, index: int):
        """Pula para o índice N, consumindo todos os anteriores."""
        if not (0 <= index < len(self._items)):
            return
        self._advance_seq += 1  # invalida qualquer end-file pendente
        # Cancela preload: o item preloaded pode não ser o destino do jump.
        # play_index vai chamar player.play() explicitamente, gerando end-file(stop).
        was_preloading = self._preloading
        self._preloading = False
        if self._running and (not was_preloading or index != 1):
            # Um loadfile replace será emitido → precisamos ignorar o end-file(stop)
            self._skip_end_file += 1
        if index > 0:
            del self._items[:index]
            self.save_schedule(self._items)
            await self._broadcast({"event": "schedule_updated", "items": list(self._items)})
        await self.play_index(0)

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
