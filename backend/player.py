"""
Camada de integração com o MPV via python-mpv.
Expõe uma interface simples de controle e registra callbacks de eventos.
"""

import os
import threading
import logging
from pathlib import Path
from typing import Callable, Optional

# Garante que libmpv-2.dll seja encontrada mesmo estando na pasta do script
_here = str(Path(__file__).parent)
os.environ["PATH"] = _here + os.pathsep + os.environ.get("PATH", "")

logger = logging.getLogger(__name__)


class Player:
    def __init__(self, on_end_file: Callable[[str], None]):
        """
        on_end_file: chamado quando o arquivo termina ou falha.
                     recebe a reason: 'eof' | 'error' | 'stop' | ...
        """
        self._on_end_file = on_end_file
        self._mpv = None
        self._lock = threading.Lock()
        self._init_mpv()

    def _init_mpv(self):
        try:
            import mpv  # raises OSError when libmpv-2.dll is missing
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
                    raw = event.get("reason") if isinstance(event, dict) else getattr(event, "reason", None)
                    s = str(raw).lower() if raw is not None else "eof"
                    if "stop" in s or "quit" in s:
                        reason = "stop"
                    elif "error" in s:
                        reason = "error"
                    else:
                        reason = "eof"
                except Exception:
                    reason = "eof"
                logger.info("end-file reason=%s", reason)
                self._on_end_file(reason)

            @self._mpv.event_callback("shutdown")
            def _shutdown_handler(event):
                logger.info("Janela MPV fechada — reinicializando")
                threading.Thread(target=self._reinit_mpv, daemon=True).start()

        except (ImportError, OSError) as exc:
            logger.warning("MPV não disponível (%s) — modo simulação ativado", exc)
            self._mpv = None

    def _reinit_mpv(self):
        import time
        time.sleep(0.2)  # aguarda MPV liberar recursos internos
        with self._lock:
            self._mpv = None
        self._init_mpv()
        logger.info("MPV reinicializado com sucesso")

    # ------------------------------------------------------------------ #
    # Callbacks internos                                                   #
    # ------------------------------------------------------------------ #

    def _mpv_log(self, level, component, message):
        logger.debug("[mpv/%s] %s", component, message.strip())

    def _on_time_pos(self, name, value):
        pass  # pode ser expandido para emitir progresso via WS

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #

    def play(self, path: str):
        """Carrega e inicia reprodução do arquivo."""
        with self._lock:
            if self._mpv:
                self._mpv.play(path)
                logger.info("Reproduzindo: %s", path)
            else:
                logger.info("[SIM] play: %s", path)

    def pause(self):
        with self._lock:
            if self._mpv:
                self._mpv.pause = True

    def resume(self):
        with self._lock:
            if self._mpv:
                self._mpv.pause = False

    def stop(self):
        with self._lock:
            if self._mpv:
                self._mpv.command("stop")

    def seek(self, seconds: float, mode: str = "absolute"):
        with self._lock:
            if self._mpv:
                self._mpv.seek(seconds, mode)

    @property
    def position(self) -> Optional[float]:
        try:
            return self._mpv.time_pos if self._mpv else None
        except Exception:
            return None

    @property
    def duration(self) -> Optional[float]:
        try:
            return self._mpv.duration if self._mpv else None
        except Exception:
            return None

    @property
    def paused(self) -> bool:
        try:
            return bool(self._mpv.pause) if self._mpv else False
        except Exception:
            return False

    def shutdown(self):
        if self._mpv:
            self._mpv.terminate()
            logger.info("MPV encerrado")
