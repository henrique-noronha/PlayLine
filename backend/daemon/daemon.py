"""MPVDaemon — processo independente que controla o MPV via python-mpv.

Sobrevive ao crash do servidor; o vídeo continua sem interrupção.
TCP 127.0.0.1:6600 — protocolo JSON por linha (newline-delimited JSON).

Comandos aceitos:
    {"action": "play",     "path": "C:\\video.mp4"}
    {"action": "preload",  "path": "C:\\next.mp4"}
    {"action": "pause"}  |  {"action": "resume"}  |  {"action": "stop"}
    {"action": "seek",    "seconds": 42.0, "mode": "absolute"}
    {"action": "get_state"}
    {"action": "list_logos"}
    {"action": "set_logo", "slot": 1, "corner": "br", "active": true, "filename": "logo.png"}

Eventos emitidos:
    {"event": "end-file",       "reason": "eof"|"stop"|"error"}
    {"event": "mpv_closed"}
    {"event": "position",       "pos": 12.5}
    {"event": "state_response", "playing_path": "...", "position": 0.0, "paused": false}
    {"event": "logo_list",      "files": ["logo.png"]}
"""

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from . import checkpoint, monitor, overlay, protocol

# Garante que backend/ está no PATH para encontrar libmpv-2.dll
_BACKEND_DIR = str(Path(__file__).parent.parent)
os.environ["PATH"] = _BACKEND_DIR + os.pathsep + os.environ.get("PATH", "")

CHECKPOINT_PATH  = Path(__file__).parent.parent / "checkpoint.json"
LOGOS_DIR        = Path(__file__).parent.parent / "logos"
_INPUT_CONF_PATH = Path(__file__).parent.parent / ".playline_input.conf"

HOST = "127.0.0.1"
PORT = 6600

try:
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

logger = logging.getLogger("mpv_daemon")


class MPVDaemon:
    def __init__(self):
        self._mpv = None
        self._mpv_dead       = False   # True após shutdown; reinit no próximo play
        self._clients: list[asyncio.StreamWriter] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_position  = 0.0
        self._checkpoint_dirty = False
        self._window_positioned = False  # move_to_tv() só roda uma vez por sessão MPV
        self._logo: dict = {
            1: {"corner": "br", "active": False, "filename": ""},
            2: {"corner": "bl", "active": False, "filename": ""},
        }
        self._resize_scheduled = False  # debounce do osd-width

    # ── Inicialização do MPV ──────────────────────────────────────────────────

    def _init_mpv(self):
        import mpv
        self._mpv_dead = False
        self._window_positioned = False
        _INPUT_CONF_PATH.write_text("CLOSE_WIN ignore\n", encoding="utf-8")

        geo = monitor.secondary_monitor_geometry()
        has_secondary = bool(geo)

        mpv_kwargs = dict(
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
            prefetch_playlist=True,
        )

        if has_secondary:
            mpv_kwargs.update(border=False, fullscreen=True, ontop=True, geometry=geo)
            logger.info("MPV geometry: %s", geo)
        else:
            mpv_kwargs.update(border=True, fullscreen=False, ontop=False, geometry="380x213")
            logger.warning(
                "Monitor secundário não detectado — MPV abrirá no principal em janela (380x213)"
            )

        self._mpv = mpv.MPV(**mpv_kwargs)
        self._mpv.observe_property("time-pos", self._on_time_pos)
        try:
            self._mpv.observe_property("osd-width", self._on_osd_resize)
        except Exception as exc:
            logger.warning("observe_property(osd-width) indisponível: %s", exc)

        @self._mpv.event_callback("file-loaded")
        def _file_loaded(event):
            if not self._window_positioned:
                threading.Thread(target=self._move_to_tv, daemon=True).start()
            if any(d["active"] for d in self._logo.values()):
                threading.Thread(target=self._apply_overlay_delayed, daemon=True).start()

        @self._mpv.event_callback("end-file")
        def _end_file(event):
            if self._mpv_dead:
                return
            reason = protocol.parse_end_reason(event)
            logger.info("end-file reason=%s", reason)
            if reason != "stop":
                checkpoint.clear(CHECKPOINT_PATH)
            self._broadcast_sync({"event": "end-file", "reason": reason})

        @self._mpv.event_callback("shutdown")
        def _shutdown(event):
            if self._mpv_dead:
                return
            self._mpv_dead = True
            logger.info("MPV encerrado — reinit ocorrerá no próximo play")
            self._broadcast_sync({"event": "mpv_closed"})

        logger.info("MPV inicializado")

    def _move_to_tv(self):
        monitor.move_window_to_secondary("PlayLine")
        self._window_positioned = True

    def _mpv_log(self, level, component, message):
        logger.debug("[mpv/%s] %s", component, message.strip())

    # ── Callbacks de propriedade MPV ─────────────────────────────────────────

    def _on_time_pos(self, name, value):
        if value is not None and not self._mpv_dead:
            self._last_position = float(value)
            self._checkpoint_dirty = True

    def _on_osd_resize(self, name, value):
        """Re-aplica overlay (com debounce) quando a janela MPV é redimensionada."""
        if value is None or not any(d["active"] for d in self._logo.values()):
            return
        if self._resize_scheduled:
            return
        self._resize_scheduled = True

        def _delayed():
            import time
            time.sleep(0.15)
            self._resize_scheduled = False
            self._apply_overlay()

        threading.Thread(target=_delayed, daemon=True).start()

    # ── Logo overlay ─────────────────────────────────────────────────────────

    def _apply_overlay(self):
        overlay.apply(self._mpv, self._logo, LOGOS_DIR)

    def _apply_overlay_delayed(self):
        import time
        time.sleep(0.5)
        self._apply_overlay()

    # ── Checkpoint ───────────────────────────────────────────────────────────

    def _write_checkpoint(self, path: str):
        checkpoint.write(CHECKPOINT_PATH, path)
        self._last_position    = 0.0
        self._checkpoint_dirty = False

    def _flush_checkpoint(self):
        if not self._checkpoint_dirty:
            return
        if checkpoint.flush(CHECKPOINT_PATH, self._last_position):
            self._checkpoint_dirty = False

    # ── Broadcast TCP (MPV callbacks rodam em thread separada) ───────────────

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

    # ── Servidor TCP ─────────────────────────────────────────────────────────

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        addr = writer.get_extra_info("peername")
        logger.info("Cliente conectado: %s", addr)
        self._clients.append(writer)

        # Envia lista de logos ao conectar
        try:
            files = _list_logos(LOGOS_DIR)
            writer.write((json.dumps({"event": "logo_list", "files": files}) + "\n").encode())
            await writer.drain()
        except Exception as exc:
            logger.error("Erro ao listar logos na conexão: %s", exc)

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
            if self._mpv_dead or self._mpv is None:
                logger.info("Reinicializando MPV para reprodução...")
                self._init_mpv()
            if self._mpv:
                self._mpv.command("loadfile", path, "replace")
                self._write_checkpoint(path)
                logger.info("play: %s", path)

        elif action == "preload":
            path = cmd.get("path", "")
            if path and self._mpv and not self._mpv_dead:
                self._mpv.command("loadfile", path, "append")
                logger.info("preload: %s", path)

        elif action == "pause":
            if self._mpv and not self._mpv_dead:
                self._mpv.pause = True

        elif action == "resume":
            if self._mpv and not self._mpv_dead:
                self._mpv.pause = False

        elif action == "stop":
            if self._mpv and not self._mpv_dead:
                self._mpv.command("stop")
                for slot in (1, 2):
                    try:
                        self._mpv.command("overlay-remove", str(slot))
                    except Exception:
                        pass
            checkpoint.clear(CHECKPOINT_PATH)

        elif action == "seek":
            if self._mpv and not self._mpv_dead:
                try:
                    self._mpv.seek(cmd.get("seconds", 0.0), cmd.get("mode", "absolute"))
                except Exception as exc:
                    logger.warning("seek: %s", exc)

        elif action == "list_logos":
            try:
                files = _list_logos(LOGOS_DIR)
                writer.write((json.dumps({"event": "logo_list", "files": files}) + "\n").encode())
                await writer.drain()
            except Exception as exc:
                logger.error("Erro ao listar logos: %s", exc)

        elif action == "set_logo":
            slot = cmd.get("slot", 1)
            if slot not in (1, 2):
                logger.warning("[set_logo] slot inválido: %s", slot)
                return
            corner   = cmd.get("corner",   "br")
            active   = cmd.get("active",   False)
            filename = cmd.get("filename", "")
            logger.info("[set_logo] slot=%s filename=%r corner=%s active=%s",
                        slot, filename, corner, active)

            def _update(s=slot, c=corner, a=active, f=filename):
                self._logo[s]["corner"] = c
                self._logo[s]["active"] = a
                if f:
                    self._logo[s]["filename"] = f
                logger.info("[set_logo] estado: %s", self._logo)
                self._apply_overlay()

            threading.Thread(target=_update, daemon=True).start()

        elif action == "get_state":
            playing_path = None
            paused       = False
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
                "event":        "state_response",
                "playing_path": playing_path,
                "position":     self._last_position,
                "paused":       paused,
            }
            try:
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
            except Exception:
                pass

    # ── Tarefas assíncronas ───────────────────────────────────────────────────

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


# ── Utilitário ────────────────────────────────────────────────────────────────

def _list_logos(logos_dir: Path) -> list[str]:
    return sorted(
        f.name for f in logos_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg")
    )
