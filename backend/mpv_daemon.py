"""
MPV Daemon — processo independente que controla o MPV via python-mpv.
Sobrevive ao crash do servidor; o vídeo continua sem interrupção.

TCP 127.0.0.1:6600 — protocolo JSON por linha (newline-delimited JSON).

Comandos:  {"action": "play", "path": "C:\\video.mp4"}
           {"action": "pause"}  |  {"action": "resume"}  |  {"action": "stop"}
           {"action": "seek", "seconds": 42.0, "mode": "absolute"}
           {"action": "get_state"}

Eventos:   {"event": "end-file", "reason": "eof"|"stop"|"error"}
           {"event": "mpv_closed"}
           {"event": "state_response", "playing_path": "...", "position": 0.0, "paused": false}
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

# libmpv-2.dll fica em backend/ (mesmo diretório deste script)
_here = str(Path(__file__).parent)
os.environ["PATH"] = _here + os.pathsep + os.environ.get("PATH", "")

CHECKPOINT_PATH  = Path(__file__).parent / "checkpoint.json"
_INPUT_CONF_PATH = Path(__file__).parent / ".playline_input.conf"
HOST = "127.0.0.1"
PORT = 6600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [mpv-daemon] %(levelname)s: %(message)s",
)
logger = logging.getLogger("mpv_daemon")


class MPVDaemon:
    def __init__(self):
        self._mpv = None
        self._mpv_dead = False          # True após shutdown; reinit ocorre no próximo play
        self._clients: list[asyncio.StreamWriter] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_position: float = 0.0
        self._checkpoint_dirty = False

    # MPV                                                                  #

    def _init_mpv(self):
        import mpv
        self._mpv_dead = False
        _INPUT_CONF_PATH.write_text("CLOSE_WIN ignore\n", encoding="utf-8")
        self._mpv = mpv.MPV(
            ytdl=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            input_conf=str(_INPUT_CONF_PATH),
            video_sync="display-resample",
            hr_seek="yes",
            keep_open=False,
            idle=True,
            title="PlayLine",
            log_handler=self._mpv_log,
            loglevel="warn",
        )
        self._mpv.observe_property("time-pos", self._on_time_pos)

        @self._mpv.event_callback("end-file")
        def _end_file(event):
            if self._mpv_dead:
                return  # ignora eventos do MPV antigo durante reinit
            reason = _parse_end_reason(event)
            logger.info("end-file reason=%s", reason)
            if reason != "stop":
                _clear_checkpoint(CHECKPOINT_PATH)
            self._broadcast_sync({"event": "end-file", "reason": reason})

        @self._mpv.event_callback("shutdown")
        def _shutdown(event):
            if self._mpv_dead:
                return  # já processado, ignora disparo duplo do GC
            self._mpv_dead = True
            logger.info("MPV encerrado — reinit ocorrerá no próximo play")
            self._broadcast_sync({"event": "mpv_closed"})

        logger.info("MPV inicializado")

    def _mpv_log(self, level, component, message):
        logger.debug("[mpv/%s] %s", component, message.strip())

    def _on_time_pos(self, name, value):
        if value is not None and not self._mpv_dead:
            self._last_position = float(value)
            self._checkpoint_dirty = True

    # Checkpoint                                                           #

    def _write_checkpoint(self, path: str):
        try:
            CHECKPOINT_PATH.write_text(
                json.dumps({"path": path, "position": 0.0}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        self._last_position = 0.0
        self._checkpoint_dirty = False

    def _flush_checkpoint(self):
        if not self._checkpoint_dirty:
            return
        try:
            data = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
            data["position"] = self._last_position
            CHECKPOINT_PATH.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            self._checkpoint_dirty = False
        except Exception:
            pass

    # Broadcast (MPV callbacks rodam em thread separada)                  #

    def _broadcast_sync(self, data: dict):
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._broadcast(data), self._loop)

    async def _broadcast(self, data: dict):
        payload = (json.dumps(data) + "\n").encode()
        dead = []
        for w in self._clients:
            try:
                w.write(payload)
                await w.drain()
            except Exception:
                dead.append(w)
        for w in dead:
            if w in self._clients:
                self._clients.remove(w)

    # Clientes TCP                                                         #

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        addr = writer.get_extra_info("peername")
        logger.info("Cliente conectado: %s", addr)
        self._clients.append(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line = line.strip()
                if line:
                    try:
                        await self._handle_command(json.loads(line), writer)
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            logger.debug("Erro no cliente %s: %s", addr, exc)
        finally:
            if writer in self._clients:
                self._clients.remove(writer)
            try:
                writer.close()
            except Exception:
                pass
            logger.info("Cliente desconectado: %s", addr)

    async def _handle_command(self, cmd: dict, writer: asyncio.StreamWriter):
        action = cmd.get("action")

        if action == "play":
            path = cmd.get("path", "")
            if not path:
                return
            # Reinicializa MPV se a janela foi fechada pelo usuário
            if self._mpv_dead or self._mpv is None:
                logger.info("Reinicializando MPV para reprodução...")
                self._init_mpv()
            if self._mpv:
                self._mpv.play(path)
                self._write_checkpoint(path)
                logger.info("play: %s", path)

        elif action == "pause":
            if self._mpv and not self._mpv_dead:
                self._mpv.pause = True

        elif action == "resume":
            if self._mpv and not self._mpv_dead:
                self._mpv.pause = False

        elif action == "stop":
            if self._mpv and not self._mpv_dead:
                self._mpv.command("stop")
            _clear_checkpoint(CHECKPOINT_PATH)

        elif action == "seek":
            if self._mpv and not self._mpv_dead:
                try:
                    self._mpv.seek(cmd.get("seconds", 0.0), cmd.get("mode", "absolute"))
                except Exception as exc:
                    logger.warning("seek: %s", exc)

        elif action == "get_state":
            playing_path = None
            paused = False
            if self._mpv and not self._mpv_dead:
                try:
                    playing_path = self._mpv.path
                except Exception:
                    pass
                try:
                    paused = bool(self._mpv.pause)
                except Exception:
                    pass
            resp = {
                "event": "state_response",
                "playing_path": playing_path,
                "position": self._last_position,
                "paused": paused,
            }
            try:
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
            except Exception:
                pass

    # Lifecycle                                                            #

    async def _checkpoint_task(self):
        while True:
            await asyncio.sleep(5)
            self._flush_checkpoint()

    async def _position_task(self):
        while True:
            await asyncio.sleep(0.5)
            if self._mpv and not self._mpv_dead:
                try:
                    pos = self._mpv.time_pos
                    if pos is not None:
                        await self._broadcast({"event": "position", "pos": round(float(pos), 2)})
                except Exception:
                    pass

    async def serve(self):
        self._loop = asyncio.get_event_loop()
        self._init_mpv()
        server = await asyncio.start_server(self.handle_client, HOST, PORT)
        logger.info("MPV Daemon escutando em %s:%d — PID %d", HOST, PORT, os.getpid())
        asyncio.create_task(self._checkpoint_task())
        asyncio.create_task(self._position_task())
        async with server:
            await server.serve_forever()


# Helpers                                                              #

def _parse_end_reason(event) -> str:
    try:
        raw = None
        if isinstance(event, dict):
            raw = event.get("reason")
            if raw is None:
                evt = event.get("event")
                raw = (
                    evt.get("reason")
                    if isinstance(evt, dict)
                    else getattr(evt, "reason", None)
                )
        else:
            raw = getattr(event, "reason", None)
            if raw is None:
                data = getattr(event, "data", None)
                if data is not None:
                    raw = getattr(data, "reason", None)
        s = str(raw).lower() if raw is not None else ""
        try:
            r = int(raw)
        except (TypeError, ValueError):
            r = -1
        if r in (2, 3) or "stop" in s or "quit" in s:
            return "stop"
        if r == 4 or "error" in s:
            return "error"
        return "eof"
    except Exception:
        return "eof"


def _clear_checkpoint(path_obj: Path):
    try:
        path_obj.unlink(missing_ok=True)
    except Exception:
        pass


if __name__ == "__main__":
    daemon = MPVDaemon()
    try:
        asyncio.run(daemon.serve())
    except KeyboardInterrupt:
        logger.info("Daemon encerrado")
