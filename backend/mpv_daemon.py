"""
MPV Daemon — processo independente que controla o MPV via python-mpv.
Sobrevive ao crash do servidor; o vídeo continua sem interrupção.

TCP 127.0.0.1:6600 — protocolo JSON por linha (newline-delimited JSON).

Comandos:  {"action": "play", "path": "C:\\video.mp4"}
           {"action": "pause"}  |  {"action": "resume"}  |  {"action": "stop"}
           {"action": "seek", "seconds": 42.0, "mode": "absolute"}
           {"action": "get_state"}
           {"action": "list_logos"}
           {"action": "set_logo", "slot": 1, "corner": "br", "active": true, "filename": "logo.png"}

Eventos:   {"event": "end-file", "reason": "eof"|"stop"|"error"}
           {"event": "mpv_closed"}
           {"event": "state_response", "playing_path": "...", "position": 0.0, "paused": false}
           {"event": "logo_list", "files": ["logo.png"]}
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

# Diretório estático de onde os logos serão lidos
LOGOS_DIR = Path(__file__).parent / "logos"
try:
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

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
        self._window_positioned = False  # _move_to_tv só roda uma vez por sessão MPV
        self._logo: dict = {
            1: {"corner": "br", "active": False, "filename": ""},
            2: {"corner": "bl", "active": False, "filename": ""},
        }
        self._resize_scheduled: bool = False  # debounce do observe_property osd-width

    # MPV                                                                      #

    def _init_mpv(self):
        import mpv
        self._mpv_dead = False
        self._window_positioned = False
        _INPUT_CONF_PATH.write_text("CLOSE_WIN ignore\n", encoding="utf-8")

        geo = _secondary_monitor_geometry()  # ex: "+1920+0"
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
            logger.warning("Monitor secundário não detectado — MPV abrirá no monitor principal em janela (380x213)")

        self._mpv = mpv.MPV(**mpv_kwargs)
        self._mpv.observe_property("time-pos", self._on_time_pos)
        try:
            self._mpv.observe_property("osd-width", self._on_osd_resize)
        except Exception as exc:
            logger.warning("observe_property(osd-width) indisponível: %s", exc)

        @self._mpv.event_callback("file-loaded")
        def _file_loaded(event):
            import threading
            if not self._window_positioned:
                threading.Thread(target=self._move_to_tv, daemon=True).start()
            if any(d["active"] for d in self._logo.values()):
                threading.Thread(target=self._apply_overlay_delayed, daemon=True).start()

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

    def _move_to_tv(self):
        """Posiciona a janela MPV no monitor secundário SEM toggle de fullscreen.
        O toggle fullscreen=False→True em HDMI invalida o VO e fecha o MPV.
        Usamos SetWindowPos diretamente para mover sem tocar no estado do MPV.
        """
        import ctypes
        import time

        rect = _get_secondary_monitor_rect()
        if not rect:
            logger.info("Monitor secundário não encontrado")
            self._window_positioned = True
            return

        hwnd = None
        for _ in range(30):
            hwnd = ctypes.windll.user32.FindWindowW(None, "PlayLine")
            if hwnd:
                break
            time.sleep(0.1)

        if not hwnd:
            logger.warning("Janela MPV não encontrada para reposicionar")
            self._window_positioned = True
            return

        left, top, right, bottom = rect
        width  = right - left
        height = bottom - top
        logger.info("Posicionando MPV no monitor secundário: %dx%d+%d+%d",
                    width, height, left, top)

        # HWND_TOPMOST=-1, SWP_NOACTIVATE=0x0010, SWP_SHOWWINDOW=0x0040
        ctypes.windll.user32.SetWindowPos(
            hwnd, ctypes.c_int(-1),
            left, top, width, height,
            0x0010 | 0x0040,
        )
        self._window_positioned = True

    def _apply_overlay(self):
        """Aplica logos via overlay-add com BGRA pré-multiplicado."""
        if not self._mpv or self._mpv_dead:
            logger.warning("[overlay] MPV não disponível (dead=%s)", self._mpv_dead)
            return

        import tempfile
        from pathlib import Path as _Path

        # Remove overlays anteriores
        for slot in (1, 2):
            try:
                self._mpv.command('overlay-remove', str(slot))
            except Exception:
                pass

        # overlay-add usa coordenadas OSD (tamanho real da janela/display)
        try:
            osd_w = int(self._mpv.osd_width or self._mpv.width or 1920)
            osd_h = int(self._mpv.osd_height or self._mpv.height or 1080)
        except Exception:
            osd_w, osd_h = 1920, 1080
        logger.info("[overlay] dimensões OSD: %dx%d", osd_w, osd_h)

        # Replica o CSS do player: max-height 14%, max-width 30%, object-fit contain
        # Margem: 4% horizontal (left/right), 5% vertical (top/bottom) — igual ao CSS
        max_logo_h = max(1, int(osd_h * 0.14))
        max_logo_w = max(1, int(osd_w * 0.30))
        margin_x   = max(4, int(osd_w * 0.04))
        margin_y   = max(4, int(osd_h * 0.05))

        qualquer_ativo = False

        for slot in (1, 2):
            s = self._logo[slot]
            logger.info("[overlay] slot=%d active=%s filename=%r", slot, s["active"], s["filename"])

            if not s["active"] or not s["filename"]:
                continue

            p = LOGOS_DIR / s["filename"]
            if not p.is_file():
                logger.error("[overlay] slot=%d arquivo não encontrado: %s", slot, p)
                continue

            try:
                from PIL import Image
                img = Image.open(str(p)).convert("RGBA")
            except Exception as exc:
                logger.error("[overlay] slot=%d erro ao abrir imagem %s: %s", slot, p.name, exc)
                continue

            w, h = img.size

            # Replica CSS: max-height 14%, max-width 30%, object-fit contain
            ratio = min(max_logo_h / h, max_logo_w / w)
            new_w = max(1, int(w * ratio))
            new_h = max(1, int(h * ratio))
            img = img.resize((new_w, new_h), Image.LANCZOS)
            w, h = new_w, new_h
            logger.info("[overlay] slot=%d redimensionado para %dx%d (osd=%dx%d)",
                        slot, w, h, osd_w, osd_h)

            raw = img.tobytes()  # bytes RGBA

            # Converte RGBA → BGRA com alpha pré-multiplicado (exigido por overlay-add)
            buf = bytearray(len(raw))
            for i in range(0, len(raw), 4):
                r, g, b, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
                fa = a / 255.0
                buf[i]     = int(b * fa)
                buf[i + 1] = int(g * fa)
                buf[i + 2] = int(r * fa)
                buf[i + 3] = a

            stride = w * 4
            tmp = _Path(tempfile.gettempdir()) / f"playline_logo_{slot}.bgra"
            tmp.write_bytes(bytes(buf))

            corner = s["corner"]
            if corner == "tl":
                x, y = margin_x, margin_y
            elif corner == "tr":
                x, y = osd_w - w - margin_x, margin_y
            elif corner == "bl":
                x, y = margin_x, osd_h - h - margin_y
            else:  # br
                x, y = osd_w - w - margin_x, osd_h - h - margin_y

            x, y = max(0, x), max(0, y)

            try:
                self._mpv.command(
                    'overlay-add',
                    str(slot), str(x), str(y),
                    str(tmp), '0',
                    'bgra',
                    str(w), str(h), str(stride),
                )
                logger.info("[overlay] slot=%d OK pos=(%d,%d) %dx%d arquivo=%s",
                            slot, x, y, w, h, p.name)
                qualquer_ativo = True
            except Exception as exc:
                logger.error("[overlay] overlay-add slot=%d FALHOU: %s", slot, exc)

        if not qualquer_ativo:
            logger.info("[overlay] nenhum overlay aplicado")

    def _apply_overlay_delayed(self):
        """Re-aplica overlay após breve delay (chamado no file-loaded)."""
        import time
        time.sleep(0.5)
        self._apply_overlay()

    def _clear_vf(self):
        if not self._mpv or self._mpv_dead:
            return
        try:
            self._mpv.vf = ""
        except Exception:
            pass

    def _mpv_log(self, level, component, message):
        logger.debug("[mpv/%s] %s", component, message.strip())

    def _on_time_pos(self, name, value):
        if value is not None and not self._mpv_dead:
            self._last_position = float(value)
            self._checkpoint_dirty = True

    def _on_osd_resize(self, name, value):
        """Recalcula e re-aplica overlay quando a janela MPV é redimensionada."""
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
        import threading
        threading.Thread(target=_delayed, daemon=True).start()

    # Checkpoint                                                               #

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

    # Broadcast (MPV callbacks rodam em thread separada)                       #

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

    # Clientes TCP                                                             #

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        addr = writer.get_extra_info("peername")
        logger.info("Cliente conectado: %s", addr)
        self._clients.append(writer)

        # Envia a lista de logos imediatamente quando a interface se conecta
        try:
            files = [f.name for f in LOGOS_DIR.iterdir() if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg')]
            resp = {"event": "logo_list", "files": files}
            writer.write((json.dumps(resp) + "\n").encode())
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
            # Reinicializa MPV se a janela foi fechada pelo usuário
            if self._mpv_dead or self._mpv is None:
                logger.info("Reinicializando MPV para reprodução...")
                self._init_mpv()
            if self._mpv:
                # "replace" limpa a playlist interna e começa do zero
                self._mpv.command("loadfile", path, "replace")
                self._write_checkpoint(path)
                logger.info("play: %s", path)

        elif action == "preload":
            path = cmd.get("path", "")
            if path and self._mpv and not self._mpv_dead:
                # "append" enfileira o próximo vídeo; MPV transita sem flash
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
                        self._mpv.command('overlay-remove', str(slot))
                    except Exception:
                        pass
            _clear_checkpoint(CHECKPOINT_PATH)

        elif action == "seek":
            if self._mpv and not self._mpv_dead:
                try:
                    self._mpv.seek(cmd.get("seconds", 0.0), cmd.get("mode", "absolute"))
                except Exception as exc:
                    logger.warning("seek: %s", exc)

        elif action == "list_logos":
            try:
                files = [f.name for f in LOGOS_DIR.iterdir() if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg')]
                resp = {"event": "logo_list", "files": files}
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
            except Exception as exc:
                logger.error("Erro ao listar logos: %s", exc)

        elif action == "set_logo":
            slot = cmd.get("slot", 1)
            corner = cmd.get("corner", "br")
            active = cmd.get("active", False)
            filename = cmd.get("filename", "")

            logger.info("[set_logo] recebido: slot=%s filename=%r corner=%s active=%s",
                        slot, filename, corner, active)

            if slot not in (1, 2):
                logger.warning("[set_logo] slot inválido: %s", slot)
                return

            def _update(s=slot, c=corner, a=active, f=filename):
                self._logo[s]["corner"] = c
                self._logo[s]["active"] = a
                if f:
                    self._logo[s]["filename"] = f
                logger.info("[set_logo] estado atualizado: %s", self._logo)
                self._apply_overlay()

            import threading
            threading.Thread(target=_update, daemon=True).start()

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

    # Lifecycle                                                                #

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


# Helpers                                                                  #

def _get_secondary_monitor_rect():
    """Returns (left, top, right, bottom) of the secondary monitor, or None."""
    try:
        import ctypes
        import ctypes.wintypes
        monitors = []
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.wintypes.RECT),
            ctypes.c_double,
        )
        def _cb(_hMon, _hdcMon, lprc, _data):
            r = lprc.contents
            monitors.append((r.left, r.top, r.right, r.bottom))
            return True
        ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
        for left, top, right, bottom in monitors:
            if left != 0 or top != 0:
                return (left, top, right, bottom)
        if len(monitors) >= 2:
            return monitors[1]
    except Exception as exc:
        logger.warning("Não foi possível detectar monitor secundário: %s", exc)
    return None


def _secondary_monitor_geometry() -> str:
    """Retorna geometry MPV com resolução e posição do monitor secundário.
    Formato 'WxH+X+Y' (ex: '1920x1080+1920+0') — mais confiável que só '+X+Y'
    porque o MPV sabe exatamente onde e com que tamanho abrir a janela.
    """
    rect = _get_secondary_monitor_rect()
    if not rect:
        return ""
    left, top, right, bottom = rect
    w = right - left
    h = bottom - top
    return f"{w}x{h}+{left}+{top}"


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