"""
Camada de integração com o MPV via python-mpv.
Expõe uma interface simples de controle e registra callbacks de eventos.
"""

import os
import threading
import logging
from pathlib import Path
from typing import Callable, Optional

# libmpv-2.dll fica em backend/, um nível acima deste arquivo
_here = str(Path(__file__).parent.parent)
os.environ["PATH"] = _here + os.pathsep + os.environ.get("PATH", "")

logger = logging.getLogger(__name__)


class Player:
    def __init__(self, on_end_file: Callable[[str], None]):
        self._on_end_file = on_end_file
        self._mpv = None
        self._lock = threading.Lock()
        self._dead = False  # True quando a janela foi fechada pelo X
        self._init_mpv()

    def _init_mpv(self):
        self._dead = False
        try:
            import mpv
            self._mpv = mpv.MPV(
                ytdl=False,
                input_default_bindings=False,
                input_vo_keyboard=False,
                video_sync="display-resample",
                hr_seek="yes",
                keep_open=False,
                idle=True,
                log_handler=self._mpv_log,
                loglevel="warn",
            )
            self._mpv.observe_property("time-pos", self._on_time_pos)

            @self._mpv.event_callback("end-file")
            def _end_file_handler(event):
                try:
                    raw = None
                    if isinstance(event, dict):
                        raw = event.get("reason")
                        if raw is None:
                            evt = event.get("event")
                            raw = evt.get("reason") if isinstance(evt, dict) else getattr(evt, "reason", None)
                    else:
                        raw = getattr(event, "reason", None)

                    s = str(raw).lower() if raw is not None else ""
                    try:
                        r = int(raw)
                    except (TypeError, ValueError):
                        r = -1

                    # libmpv: EOF=0, STOP=2, QUIT=3, ERROR=4
                    if r in (2, 3) or "stop" in s or "quit" in s:
                        reason = "stop"
                    elif r == 4 or "error" in s:
                        reason = "error"
                    else:
                        reason = "eof"
                except Exception:
                    reason = "eof"
                logger.info("end-file raw=%r reason=%s", raw, reason)
                self._on_end_file(reason)

            @self._mpv.event_callback("shutdown")
            def _shutdown_handler(event):
                self._dead = True
                logger.info("Janela MPV fechada pelo usuário")

        except (ImportError, OSError) as exc:
            logger.warning("MPV não disponível (%s) — modo simulação ativado", exc)
            self._mpv = None

    # ------------------------------------------------------------------ #
    # Callbacks internos                                                   #
    # ------------------------------------------------------------------ #

    def _mpv_log(self, level, component, message):
        logger.debug("[mpv/%s] %s", component, message.strip())

    def _on_time_pos(self, name, value):
        pass

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #

    def play(self, path: str):
        with self._lock:
            if self._dead or self._mpv is None:
                logger.info("Reinicializando MPV antes de reproduzir...")
                self._mpv = None
                self._init_mpv()
            if self._mpv:
                self._mpv.play(path)
                logger.info("Reproduzindo: %s", path)
            else:
                logger.info("[SIM] play: %s", path)

    def pause(self):
        with self._lock:
            if self._mpv and not self._dead:
                self._mpv.pause = True

    def resume(self):
        with self._lock:
            if self._mpv and not self._dead:
                self._mpv.pause = False

    def stop(self):
        with self._lock:
            if self._mpv and not self._dead:
                self._mpv.command("stop")

    def seek(self, seconds: float, mode: str = "absolute"):
        with self._lock:
            if self._mpv and not self._dead:
                self._mpv.seek(seconds, mode)

    @property
    def position(self) -> Optional[float]:
        try:
            return self._mpv.time_pos if self._mpv and not self._dead else None
        except Exception:
            return None

    @property
    def duration(self) -> Optional[float]:
        try:
            return self._mpv.duration if self._mpv and not self._dead else None
        except Exception:
            return None

    @property
    def paused(self) -> bool:
        try:
            return bool(self._mpv.pause) if self._mpv and not self._dead else False
        except Exception:
            return False

    def shutdown(self):
        if self._mpv:
            self._mpv.terminate()
            logger.info("MPV encerrado")
