"""
Player — cliente TCP para o MPV Daemon (processo separado).
Conecta-se a 127.0.0.1:6600; se o daemon não estiver rodando, inicia-o.
O daemon sobrevive ao crash do servidor
"""

import json
import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 6600
_DAEMON_SCRIPT = Path(__file__).parent.parent / "mpv_daemon.py"

logger = logging.getLogger(__name__)


class Player:
    def __init__(self, on_end_file: Callable[[str], None], on_position: Optional[Callable[[float], None]] = None, on_logo_list: Optional[Callable[[list], None]] = None):
        self._on_end_file = on_end_file
        self._on_position = on_position
        self._on_logo_list = on_logo_list
        self._sock: Optional[socket.socket] = None
        self._send_lock = threading.Lock()
        self._connected = False
        self._buf = b""
        self._pending_state_event: Optional[threading.Event] = None
        self._pending_state_path: Optional[str] = None
        self._connect_or_start()

    # Conexão                                                              #

    def _connect_or_start(self):
        if self._try_connect():
            logger.info("Conectado ao MPV Daemon existente em %s:%d", DAEMON_HOST, DAEMON_PORT)
            return
        logger.info("Daemon não encontrado — iniciando %s...", _DAEMON_SCRIPT.name)
        self._launch_daemon()
        for _ in range(30):
            time.sleep(0.3)
            if self._try_connect():
                logger.info("MPV Daemon iniciado com sucesso")
                return
        logger.error("Não foi possível conectar ao MPV Daemon após 9 s")

    def _launch_daemon(self):
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(
                [sys.executable, str(_DAEMON_SCRIPT)],
                creationflags=flags,
            )
        except Exception as exc:
            logger.error("Falha ao iniciar daemon: %s", exc)

    def _try_connect(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((DAEMON_HOST, DAEMON_PORT))
            s.settimeout(None)
            self._sock = s
            self._connected = True
            threading.Thread(target=self._read_loop, daemon=True).start()
            return True
        except (ConnectionRefusedError, OSError):
            return False

    # Leitura de eventos                                                   
   
    def _read_loop(self):
        while self._connected:
            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    logger.warning("MPV Daemon encerrou a conexão")
                    self._connected = False
                    break
                self._buf += chunk
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            self._handle_event(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            except Exception as exc:
                if self._connected:
                    logger.error("Erro de leitura: %s", exc)
                self._connected = False
                break

    def _handle_event(self, msg: dict):
        event = msg.get("event")
        if event == "end-file":
            self._on_end_file(msg.get("reason", "eof"))
        elif event == "mpv_closed":
            self._on_end_file("mpv_closed")
        elif event == "position":
            if self._on_position:
                self._on_position(msg.get("pos", 0.0))
        elif event == "state_response":
            self._pending_state_path = msg.get("playing_path")
            if self._pending_state_event:
                self._pending_state_event.set()
        elif event == "logo_list":
            if self._on_logo_list:
                self._on_logo_list(msg.get("files", []))

    # Envio                                                                #

    def _send(self, cmd: dict):
        if not self._connected or self._sock is None:
            logger.debug("Daemon não conectado — ignorando: %s", cmd.get("action"))
            return
        with self._send_lock:
            try:
                self._sock.sendall((json.dumps(cmd) + "\n").encode())
            except Exception as exc:
                logger.error("Erro ao enviar: %s", exc)
                self._connected = False

    # Consulta de estado (bloqueante — chamar via run_in_executor)        #

    def get_playing_path(self) -> Optional[str]:
        """Retorna o caminho do arquivo que o daemon está reproduzindo, ou None."""
        if not self._connected:
            return None
        evt = threading.Event()
        self._pending_state_path = None
        self._pending_state_event = evt
        self._send({"action": "get_state"})
        evt.wait(timeout=2.0)
        self._pending_state_event = None
        return self._pending_state_path

    # API pública                                                          #

    def play(self, path: str):
        self._send({"action": "play", "path": path})
        logger.info("Reproduzindo: %s", path)

    def preload(self, path: str):
        self._send({"action": "preload", "path": path})
        logger.info("Pré-carregando: %s", path)

    def pause(self):
        self._send({"action": "pause"})

    def resume(self):
        self._send({"action": "resume"})

    def stop(self):
        self._send({"action": "stop"})

    def seek(self, seconds: float, mode: str = "absolute"):
        self._send({"action": "seek", "seconds": seconds, "mode": mode})

    @property
    def position(self) -> Optional[float]:
        return None

    @property
    def duration(self) -> Optional[float]:
        return None

    @property
    def paused(self) -> bool:
        return False

    def set_volume(self, volume: int):
        self._send({"action": "set_volume", "volume": volume})

    def set_logo(self, slot: int, filename: str, corner: str, active: bool):
        logger.info("[set_logo] slot=%d filename=%r corner=%s active=%s", slot, filename, corner, active)
        self._send({"action": "set_logo", "slot": slot, "filename": filename, "corner": corner, "active": active})

    def request_logo_list(self):
        self._send({"action": "list_logos"})

    def shutdown(self):
        """Fecha a conexão com o daemon (daemon continua rodando independentemente)."""
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        logger.info("Conexão com MPV Daemon encerrada (daemon continua rodando)")
