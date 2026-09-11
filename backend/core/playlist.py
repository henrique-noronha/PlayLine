"""
Playlist Engine — gerencia a fila de reprodução e responde a eventos do Player.
"""

import json
import logging
import asyncio
import os
import socket
import time
from typing import Callable, Optional

from .db import get_conn, SCHEDULE_COLUMNS
from .history import HistoryManager
from . import settings as app_settings

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


def _is_capture_item(item: dict) -> bool:
    return (item.get("path") or "").lower().startswith("av://dshow:")


# Tempo pro navegador soltar visualmente o preview de captura antes do MPV tentar
# abrir o dispositivo. Não elimina o retry (ver comentário em play_index), só
# evita a sobreposição visual de dois consumidores.
_CAPTURE_RELEASE_DELAY = 0.3

# Watchdog de clipe local: se a posição reportada pelo MPV não avança por esse
# tempo num item não-live (rodando, não pausado), o MPV travou nesse arquivo sem
# emitir end-file (arquivo corrompido, decoder preso) e o playout avança sozinho.
# Lives têm o próprio watchdog (_live_watchdog_loop, STALL_SEC=90).
_LOCAL_STALL_SEC = 20
_STALL_CHECK_SEC = 5

# Reabertura automática quando o MPV encerra no meio de um item: no máximo
# _MPV_REOPEN_MAX vezes por _MPV_REOPEN_WINDOW s antes de desistir e parar,
# pra não ficar em loop se o MPV estiver crashando de imediato.
_MPV_REOPEN_DELAY  = 2.0
_MPV_REOPEN_MAX    = 3
_MPV_REOPEN_WINDOW = 60.0


def _item_extra(item: dict) -> Optional[str]:
    """Serializa em JSON as chaves do item sem coluna própria (type, clip_overlays...)."""
    rest = {k: v for k, v in item.items() if k not in SCHEDULE_COLUMNS and k != "extra"}
    return json.dumps(rest, ensure_ascii=False) if rest else None


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
        self._repeat: bool = False
        self._live_last_pos: float = -1.0
        self._live_pos_ts: float = 0.0
        self._last_position: float = 0.0  # posição (s) do item atual — permite reconstruir o tempo decorrido ao reconectar a interface
        self._live_watchdog_task: Optional[asyncio.Task] = None
        self._live_reconnecting: bool = False  # True quando _schedule_reconnect emitiu loadfile replace
        # Watchdog de clipe local (ver _LOCAL_STALL_SEC)
        self._pos_last: float = -1.0
        self._pos_ts: float = time.monotonic()
        self._stall_task: Optional[asyncio.Task] = None
        self._mpv_reopen_ts: list[float] = []  # janela deslizante de reaberturas após mpv_closed
        # Transição global (corte seco / fade para preto); por item: chave "transition" no roteiro
        self._transition: dict = app_settings.get_transition()

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
                extra = item.pop("extra", None)
                if extra:
                    try:
                        item.update(json.loads(extra))
                    except Exception:
                        logger.warning("Campo extra inválido no item %s — ignorado", item.get("id"))
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
                        "INSERT INTO schedule (position,id,title,path,live,start_time,end_time,duration,extra)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        [(i, it.get("id", ""), it.get("title", ""), it.get("path", ""),
                          1 if it.get("live") else 0,
                          it.get("start_time"), it.get("end_time"), it.get("duration"),
                          _item_extra(it))
                         for i, it in enumerate(items)],
                    )
        except Exception as exc:
            logger.error("Falha ao salvar roteiro: %s", exc)
        logger.info("Roteiro salvo: %d itens", len(items))
        self._maybe_prefetch_yt()
        if self._running:
            self._push_next_transition()   # o override do próximo item pode ter mudado

    def get_schedule(self) -> list[dict]:
        return self._items

    def _push_next_transition(self, index: Optional[int] = None):
        """Avisa o daemon qual transição vale na próxima fronteira (override do próximo item ou None = global)."""
        idx = self._index if index is None else index
        nxt = self._items[idx + 1] if 0 <= idx and idx + 1 < len(self._items) else None
        self._player.set_next_transition((nxt or {}).get("transition"))

    async def set_transition(self, cfg: dict) -> dict:
        """Transição global: persiste, aplica no daemon e avisa todas as interfaces. ValueError se inválida."""
        self._transition = app_settings.set_transition(cfg)
        self._player.set_transition(self._transition)
        await self._broadcast({"event": "transition_state", "transition": dict(self._transition)})
        logger.info("Transição global: %s (%.2fs)", self._transition["type"], self._transition["duration"])
        return self._transition

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
            self._maybe_resume_from_checkpoint()
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
        if self._stall_task is None and loop.is_running():
            self._stall_task = loop.create_task(self._stall_watchdog_loop())

    def on_position(self, pos: float):
        """Chamado pelo Player a cada evento de posição do MPV."""
        if self._running and 0 <= self._index < len(self._items):
            self._last_position = pos
            if abs(pos - self._pos_last) > 0.05:
                self._pos_last = pos
                self._pos_ts = time.monotonic()
            if _is_live_item(self._items[self._index]):
                if abs(pos - self._live_last_pos) > 0.05:
                    self._live_last_pos = pos
                    self._live_pos_ts = time.monotonic()

    def on_file_loaded(self):
        """Chamado pelo Player quando o MPV sinaliza file-loaded."""
        self._pos_last = -1.0
        self._pos_ts = time.monotonic()
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

    def _maybe_resume_from_checkpoint(self):
        """Daemon ocioso na inicialização: se sobrou checkpoint, a reprodução foi
        interrompida de forma anormal (queda de energia, processo morto) e o
        playout retoma sozinho no mesmo item/posição.

        O checkpoint é limpo em eof/erro e no stop manual, então só sobrevive a
        uma interrupção anormal. PLAYLINE_AUTORESUME=0 desliga (operação assistida).
        """
        if os.environ.get("PLAYLINE_AUTORESUME", "1") == "0":
            logger.info("Daemon ocioso — aguardando comando de play (auto-resume desligado)")
            return
        cp = self._read_checkpoint()
        idx = -1
        if cp and cp.get("path"):
            idx = next((i for i, it in enumerate(self._items) if it.get("path") == cp["path"]), -1)
        if idx < 0 or not self._loop:
            logger.info("Daemon ocioso — aguardando comando de play")
            return
        logger.warning("Checkpoint de reprodução interrompida encontrado (%s, %.0fs) — retomando",
                       cp["path"], cp.get("position") or 0.0)
        asyncio.run_coroutine_threadsafe(self.play_index(idx), self._loop)

    def _allow_mpv_reopen(self) -> bool:
        now = time.monotonic()
        self._mpv_reopen_ts = [t for t in self._mpv_reopen_ts if now - t < _MPV_REOPEN_WINDOW]
        if len(self._mpv_reopen_ts) >= _MPV_REOPEN_MAX:
            return False
        self._mpv_reopen_ts.append(now)
        return True

    async def _on_mpv_closed(self):
        self._cancel_live_watchdog()
        self._advance_seq += 1  # invalida qualquer avanço pendente
        self._preloading = False
        self._history.close_entry("interrupted")
        await self._broadcast({"event": "mpv_closed"})

        # MPV encerrou no meio da reprodução (crash): reabre o item atual em vez
        # de parar e esperar um play manual. O daemon reinicializa o MPV no
        # próximo play. Limite de tentativas evita loop se o MPV cair na hora.
        was_running, idx = self._running, self._index
        if was_running and 0 <= idx < len(self._items) and self._allow_mpv_reopen():
            logger.warning("MPV encerrou durante a reprodução — reabrindo o item %d em %.0fs", idx, _MPV_REOPEN_DELAY)
            await asyncio.sleep(_MPV_REOPEN_DELAY)
            if self._running and self._index == idx:  # ninguém deu stop/jump nesse meio-tempo
                await self.play_index(idx)
                return

        self._running = False
        self._paused = False
        self._index = -1
        await self._broadcast({"event": "stopped"})
        logger.info("Playout parado (janela MPV fechada)")

    def _local_stalled(self, now: float) -> bool:
        """True se o item atual é um clipe local com a posição parada há mais de _LOCAL_STALL_SEC."""
        if not (self._running and not self._paused and 0 <= self._index < len(self._items)):
            return False
        if _is_live_item(self._items[self._index]):
            return False
        return (now - self._pos_ts) > _LOCAL_STALL_SEC

    async def _stall_watchdog_loop(self):
        while True:
            await asyncio.sleep(_STALL_CHECK_SEC)
            try:
                if not self._local_stalled(time.monotonic()):
                    continue
                if not getattr(self._player, "_connected", True):
                    # Sem daemon não adianta avançar: player.py já está relançando/reconectando.
                    continue
                item = self._items[self._index]
                logger.error("Clipe local sem avanço de posição há %ds (%s) — avançando",
                             _LOCAL_STALL_SEC, item.get("title") or item.get("path"))
                self._pos_ts = time.monotonic()
                self._history.close_entry("error")
                await self._advance(expected_seq=self._advance_seq)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[watchdog] erro: %s", exc)

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
        self._last_position = 0.0
        item = self._items[index]
        self._pos_last = -1.0
        self._pos_ts = time.monotonic()
        # Reset "já tocou" ao iniciar uma live nova (não em tentativas de reconexão)
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
                if _is_capture_item(item):
                    # Dispositivo de captura (webcam/placa) aceita só um consumidor
                    # por vez. Avisa o navegador pra soltar o preview (getUserMedia)
                    # ANTES do MPV tentar abrir, em vez de só reagir depois do
                    # "now_playing" (que só é emitido depois do play()).
                    #
                    # IMPORTANTE — isso melhora a experiência (o preview não fica
                    # sobreposto no instante da troca) mas NÃO elimina a 1ª falha:
                    # testado em bancada com delays de 0.3s a 2.5s antes desta
                    # linha, e o 1º open do MPV falha de forma idêntica em todos
                    # (~500ms após o play, sempre resolvido no retry seguinte).
                    # Não é uma corrida de tempo — parece ser o Windows negociando
                    # a troca de "dono" do dispositivo entre a API do navegador
                    # (Media Foundation) e a API clássica que o MPV usa (DirectShow
                    # via ffmpeg) sempre que a primeira alguma vez tocou no
                    # dispositivo. O watchdog de reconexão existente cobre esse
                    # retry único automaticamente.
                    await self._broadcast({"event": "capture_device_releasing", "path": item["path"]})
                    await asyncio.sleep(_CAPTURE_RELEASE_DELAY)
                self._player.play(
                    item["path"],
                    start_time=item.get("start_time"),
                    end_time=item.get("end_time"),
                    force_resolve=force_resolve,
                    live=_is_live_item(item),
                    # reconexão de live: corte seco, sem fade no meio da tentativa
                    transition="cut" if force_resolve else item.get("transition"),
                )

            self._preloading = False
            self._push_next_transition(index)

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
            self._pos_ts = time.monotonic()  # tempo pausado não conta como travamento
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
            "position": self._last_position,
            "transition": dict(self._transition),
        }
