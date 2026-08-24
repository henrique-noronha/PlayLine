"""
Playlist Engine — gerencia a fila de reprodução e responde a eventos do Player.
"""

import logging
import asyncio
import socket
import time
from typing import Callable, Optional

from .db import get_conn
from .history import HistoryManager

logger = logging.getLogger(__name__)

_RECONNECT_MAX    = 5                    # tentativas antes de desistir
_RECONNECT_DELAYS = [3, 6, 12, 20, 30]  # backoff exponencial (segundos por tentativa)


def _has_internet(timeout: float = 1.5) -> bool:
    """Testa conectividade real da máquina via TCP no DNS do Google (8.8.8.8:53)."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout).close()
        return True
    except OSError:
        return False


def _is_live_item(item: dict) -> bool:
    if item.get("live"):
        return True
    path = (item.get("path") or "").lower()
    return path.startswith(("rtmp://", "rtmps://", "rtsp://"))


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
        self._reconnect_attempt: int = 0
        self._live_has_played: bool = False  # True após file-loaded confirmar a live atual
        self._live_has_played: bool = False
        self._repeat: bool = False
        self._live_last_pos: float = -1.0
        self._live_pos_ts: float = 0.0
        self._live_watchdog_task: Optional[asyncio.Task] = None
        self._live_reconnecting: bool = False  # True quando _schedule_reconnect emitiu loadfile replace

    # Roteiro                                                              #
 
    def load_schedule(self) -> list[dict]:
        try:
            conn = get_conn()
            rows = conn.execute("SELECT * FROM schedule ORDER BY position").fetchall()
            conn.close()
            self._items = []
            for r in rows:
                item = dict(r)
                item["live"] = bool(item["live"])
                self._items.append(item)
            logger.info("Roteiro carregado: %d itens", len(self._items))
        except Exception as exc:
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
        try:
            with get_conn() as conn:
                conn.execute("DELETE FROM schedule")
                if items:
                    conn.executemany(
                        "INSERT INTO schedule (position,id,title,path,live,start_time,end_time,duration)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        [(i, it.get("id", ""), it.get("title", ""), it.get("path", ""),
                          1 if it.get("live") else 0,
                          it.get("start_time"), it.get("end_time"), it.get("duration"))
                         for i, it in enumerate(items)],
                    )
        except Exception as exc:
            logger.error("Falha ao salvar roteiro: %s", exc)
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
            conn = get_conn()
            row = conn.execute("SELECT path, position FROM checkpoint WHERE id=1").fetchone()
            conn.close()
            return dict(row) if row else None
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

    def set_repeat(self, enabled: bool):
        previously = self._repeat
        self._repeat = enabled
        if not enabled and previously and 0 < self._index < len(self._items):
            # Desativando: descarta itens já reproduzidos, mantém a partir do atual
            self._items = self._items[self._index:]
            self._index = 0
            self.save_schedule(self._items)
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._broadcast({
                        "event": "schedule_updated",
                        "items": list(self._items),
                        "current_index": 0,
                    }),
                    self._loop
                )
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._broadcast({"event": "repeat", "enabled": enabled}), self._loop
            )

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def on_position(self, pos: float):
        """Chamado pelo Player a cada evento de posição do MPV."""
        if self._running and 0 <= self._index < len(self._items):
            if _is_live_item(self._items[self._index]):
                if abs(pos - self._live_last_pos) > 0.05:
                    self._live_last_pos = pos
                    self._live_pos_ts = time.monotonic()

    def on_file_loaded(self):
        """Chamado pelo Player quando o MPV sinaliza file-loaded."""
        current = self._items[self._index] if 0 <= self._index < len(self._items) else {}
        if _is_live_item(current):
            self._live_reconnecting = False  # live carregou com sucesso
            self._live_has_played = True
            self._live_last_pos = -1.0
            self._live_pos_ts = time.monotonic()
            if self._loop:
                asyncio.run_coroutine_threadsafe(self._start_live_watchdog(), self._loop)

    def on_end_file(self, reason: str):
        """Chamado pelo Player (thread de leitura TCP) quando um arquivo termina."""
        if reason == "stop":
            if self._skip_end_file > 0:
                # end-file(stop) esperado de um loadfile replace intencional
                self._skip_end_file -= 1
                return
            if self._live_reconnecting:
                # end-file(stop) do loadfile replace que a reconexão emitiu
                self._live_reconnecting = False
                return
            # "stop" sem skip pendente: MPV encerrou a live por timeout de rede
            # (reporta código 2 em vez de 4). Trata como erro para reconectar.
            current = self._items[self._index] if 0 <= self._index < len(self._items) else {}
            if not (self._running and _is_live_item(current)):
                return
            reason = "error"  # cai no bloco de reconnect abaixo
        if reason == "mpv_closed":
            self._preloading = False
            if self._loop:
                asyncio.run_coroutine_threadsafe(self._on_mpv_closed(), self._loop)
            return
        if reason in ("error", "eof"):
            self._preloading = False
            current = self._items[self._index] if 0 <= self._index < len(self._items) else {}
            if self._running and _is_live_item(current):
                self._reconnect_attempt += 1
                self._history.close_entry(reason)
                if self._reconnect_attempt <= _RECONNECT_MAX:
                    if self._loop:
                        asyncio.run_coroutine_threadsafe(
                            self._schedule_reconnect(), self._loop
                        )
                else:
                    self._reconnect_attempt = 0
                    if self._loop:
                        asyncio.run_coroutine_threadsafe(
                            self._on_reconnect_failed(), self._loop
                        )
                return
            if reason == "error":
                self._history.close_entry("error")
                logger.warning("Arquivo com erro — avançando automaticamente")
            else:
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
        self._cancel_live_watchdog()
        self._advance_seq += 1  # invalida qualquer avanço pendente
        self._running = False
        self._paused = False
        self._index = -1
        self._preloading = False
        self._history.close_entry("interrupted")
        await self._broadcast({"event": "mpv_closed"})
        await self._broadcast({"event": "stopped"})
        logger.info("Playout parado (janela MPV fechada)")

    async def _schedule_reconnect(self):
        attempt = self._reconnect_attempt
        delay   = _RECONNECT_DELAYS[min(attempt - 1, len(_RECONNECT_DELAYS) - 1)]

        # Testa conectividade real em executor para não bloquear o event loop
        loop = asyncio.get_event_loop()
        has_net     = await loop.run_in_executor(None, _has_internet)
        no_internet = not has_net
        never_played = not self._live_has_played

        if no_internet:
            label = "sem conexão com a internet"
        elif never_played:
            label = "live nunca carregou"
        else:
            label = "live caiu"

        logger.info("[reconexão] tentativa %d/%d (%s) — aguardando %ds...",
                    attempt, _RECONNECT_MAX, label, delay)

        await self._broadcast({
            "event": "stream_reconnecting",
            "attempt": attempt,
            "max_attempts": _RECONNECT_MAX,
            "delay": delay,
            "no_internet": no_internet,
            "never_played": never_played,
        })
        await asyncio.sleep(delay)
        if not self._running or not self._items:
            self._live_reconnecting = False
            return
        current = self._items[self._index] if 0 <= self._index < len(self._items) else {}
        if not _is_live_item(current):
            self._live_reconnecting = False
            return
        # Sinaliza que este loadfile replace é intencional para não disparar novo reconnect
        self._live_reconnecting = True
        await self.play_index(self._index, force_resolve=True)

    def _cancel_live_watchdog(self):
        if self._live_watchdog_task and not self._live_watchdog_task.done():
            self._live_watchdog_task.cancel()
        self._live_watchdog_task = None

    async def _start_live_watchdog(self):
        self._cancel_live_watchdog()
        self._live_watchdog_task = asyncio.ensure_future(self._live_watchdog_loop())

    async def _live_watchdog_loop(self):
        STALL_SEC = 90
        CHECK_SEC = 10
        try:
            while True:
                await asyncio.sleep(CHECK_SEC)
                if not self._running or self._index < 0:
                    return
                current = self._items[self._index] if 0 <= self._index < len(self._items) else {}
                if not _is_live_item(current):
                    return
                elapsed = time.monotonic() - self._live_pos_ts
                if elapsed > STALL_SEC:
                    logger.warning("Live stream presa há %.0fs sem avanço de posição — reconectando", elapsed)
                    self._preloading = False
                    self._reconnect_attempt += 1
                    self._history.close_entry("error")
                    if self._reconnect_attempt <= _RECONNECT_MAX:
                        asyncio.ensure_future(self._schedule_reconnect())
                    else:
                        self._reconnect_attempt = 0
                        asyncio.ensure_future(self._on_reconnect_failed())
                    return
        except asyncio.CancelledError:
            pass

    async def _on_reconnect_failed(self):
        loop = asyncio.get_event_loop()
        has_net     = await loop.run_in_executor(None, _has_internet)
        no_internet = not has_net
        never_played = not self._live_has_played
        await self._broadcast({
            "event": "stream_reconnect_failed",
            "no_internet": no_internet,
            "never_played": never_played,
        })
        logger.error("[reconexão] esgotadas %d tentativas — avançando", _RECONNECT_MAX)
        await self._advance(expected_seq=self._advance_seq)

    async def _advance(self, expected_seq: int = -1):
        """
        Consome o clipe atual e avança para o próximo.
        expected_seq >= 0: ignora se outro avanço já ocorreu (evita avanço duplo
        quando end-file natural e next/jump chegam simultaneamente).
        expected_seq = -1: avança incondicionalmente (next manual, jump).
        """
        self._live_reconnecting = False
        self._cancel_live_watchdog()
        if expected_seq >= 0 and expected_seq != self._advance_seq:
            logger.debug("_advance obsoleto (seq %d != %d) — ignorado", expected_seq, self._advance_seq)
            return
        self._advance_seq += 1

        if self._repeat:
            # Modo loop: não consome itens, avança o cursor pelo roteiro fixo
            if not self._items:
                return
            next_index = self._index + 1
            if next_index >= len(self._items):
                next_index = 0
                logger.info("Loop: reiniciando roteiro do início")
            if expected_seq < 0:
                self._preloading = False
                self._skip_end_file += 1
            self._reconnect_attempt = 0
            self._live_has_played = False
            await self.play_index(next_index)
            return

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
            self._reconnect_attempt = 0
            self._live_has_played = False
            await self.play_index(0)
        else:
            self._running = False
            self._index = -1
            self._reconnect_attempt = 0
            self._live_has_played = False
            await self._broadcast({"event": "playlist_end"})
            logger.info("Fim da playlist")

    async def play(self):
        """Inicia pelo primeiro item do roteiro."""
        self._reconnect_attempt = 0
        self._advance_seq += 1  # invalida qualquer end-file pendente
        await self.play_index(0)

    async def play_index(self, index: int, force_resolve: bool = False):
        if not (0 <= index < len(self._items)):
            return
        self._index = index
        self._running = True
        self._paused = False
        item = self._items[index]
        # Reset "já tocou" ao iniciar uma live nova (não em tentativas de reconexão)
        if _is_live_item(item) and not force_resolve:
            self._live_has_played = False

        if _is_live_item(item) and not force_resolve:
            self._live_has_played = False
            self._reconnect_attempt = 0

        if item.get("path"):
            self._history.open_entry(item.get("title") or item["path"].split("\\")[-1], item["path"])
            if self._preloading and not force_resolve:
                # MPV já avançou para este vídeo via playlist interna (pré-carregado)
                # Não chama player.play() para não interromper a reprodução
                logger.info("MPV já está em transição para: %s", item["path"])
            else:
                self._player.play(
                    item["path"],
                    start_time=item.get("start_time"),
                    end_time=item.get("end_time"),
                    force_resolve=force_resolve,
                    live=_is_live_item(item),
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
        current_path = self._items[self._index].get("path") if 0 <= self._index < len(self._items) else None
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
        self._live_reconnecting = False
        self._cancel_live_watchdog()
        self._advance_seq += 1  # invalida qualquer end-file pendente
        self._running = False
        self._paused = False
        self._index = -1
        self._preloading = False
        self._reconnect_attempt = 0
        self._live_has_played = False
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

    def request_logo_state(self):
        self._player.request_logo_state()

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
        self._live_reconnecting = False
        self._cancel_live_watchdog()
        self._advance_seq += 1  # invalida qualquer end-file pendente
        # Cancela preload: o item preloaded pode não ser o destino do jump.
        # play_index vai chamar player.play() explicitamente, gerando end-file(stop).
        was_preloading = self._preloading
        self._preloading = False
        if self._running and (not was_preloading or index != 1):
            # Um loadfile replace será emitido → precisamos ignorar o end-file(stop)
            self._skip_end_file += 1
        if self._repeat:
            # Modo loop: só muda o cursor, não remove itens
            self._reconnect_attempt = 0
            self._live_has_played = False
            await self.play_index(index)
        else:
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
            "repeat": self._repeat,
        }
