"""MPVDaemon — processo independente que controla o MPV via python-mpv.

Sobrevive ao crash do servidor; o vídeo continua sem interrupção.
TCP 127.0.0.1:6600 — protocolo JSON por linha (newline-delimited JSON).

Comandos aceitos:
    {"action": "play",       "path": "C:\\video.mp4"}
    {"action": "preload",    "path": "C:\\next.mp4"}
    {"action": "pause"}  |  {"action": "resume"}  |  {"action": "stop"}
    {"action": "seek",       "seconds": 42.0, "mode": "absolute"}
    {"action": "set_volume", "volume": 100}   -- MPV volume 0-130 (100 = 0 dB)
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
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional


from . import checkpoint, monitor, overlay, osd_text, preview, protocol, weather

# Garante que libmpv-2.dll seja encontrada (em sys._MEIPASS quando empacotado)
if getattr(sys, 'frozen', False):
    _BACKEND_DIR = str(Path(sys._MEIPASS))
    _DATA_DIR    = Path(sys.executable).parent
else:
    _BACKEND_DIR = str(Path(__file__).parent.parent)
    _DATA_DIR    = Path(__file__).parent.parent

os.environ["PATH"] = _BACKEND_DIR + os.pathsep + os.environ.get("PATH", "")

CHECKPOINT_PATH      = _DATA_DIR / "checkpoint.json"
TEXT_OVERLAY_PATH    = _DATA_DIR / "text_overlay.json"
LOGOS_DIR            = _DATA_DIR / "logos"
IMAGES_DIR           = _DATA_DIR / "images"
_INPUT_CONF_PATH     = _DATA_DIR / ".playline_input.conf"
STANDBY_SLOT         = "4"

_TEXT_OVERLAY_DEFAULTS = {
    "active":      False,
    "show_time":   True,
    "show_temp":   True,
    "corner":      "tl",
    "city":        "Palmas,TO",
    "manual_temp": "",
}

HOST = "127.0.0.1"
PORT = 6600


def _is_youtube_url(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def _is_stream_path(path: str) -> bool:
    """True para URLs de rede (HLS, RTMP, YouTube resolvido) — False para arquivos locais."""
    p = (path or "").lower().lstrip()
    return (
        p.startswith("http://") or p.startswith("https://") or
        p.startswith("rtmp://") or p.startswith("rtmps://") or
        p.startswith("rtsp://")
    )


def _resolve_yt_stream(url: str) -> str:
    """Resolve URL do YouTube para URL HLS direta. Bloqueia — chamar via executor."""
    try:
        from core.youtube_resolver import get_stream_url
    except ImportError:
        from ..core.youtube_resolver import get_stream_url
    return get_stream_url(url)


def _render_standby_overlay(osd_w: int, osd_h: int) -> Optional[tuple]:
    """Renderiza problemastecnicos.png em BGRA cover-fill para overlay-add."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("[standby] Pillow não instalado")
        return None

    img_path = IMAGES_DIR / "problemastecnicos.png"
    if not img_path.exists():
        logger.warning("[standby] imagem não encontrada: %s", img_path)
        return None

    try:
        src   = Image.open(str(img_path)).convert("RGBA")
        ratio = max(osd_w / src.width, osd_h / src.height)
        new_w = max(1, round(src.width  * ratio))
        new_h = max(1, round(src.height * ratio))
        src   = src.resize((new_w, new_h), Image.LANCZOS)

        canvas = Image.new("RGBA", (osd_w, osd_h), (0, 0, 0, 255))
        canvas.paste(src, ((osd_w - new_w) // 2, (osd_h - new_h) // 2))
    except Exception as exc:
        logger.warning("[standby] falha ao carregar imagem: %s", exc)
        return None

    rgba = canvas.tobytes()
    bgra = bytearray(len(rgba))
    for i in range(0, len(rgba), 4):
        r, g, b, a = rgba[i], rgba[i+1], rgba[i+2], rgba[i+3]
        fa = a / 255.0
        bgra[i]   = int(b * fa)
        bgra[i+1] = int(g * fa)
        bgra[i+2] = int(r * fa)
        bgra[i+3] = a

    return bytes(bgra), osd_w, osd_h


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
        self._volume: float  = 100.0   # persiste entre reinits do MPV (100 = 0 dB)
        self._logo: dict = {
            1: {"corner": "br", "active": False, "filename": ""},
            2: {"corner": "bl", "active": False, "filename": ""},
        }
        self._resize_scheduled = False  # debounce do osd-width
        self._logo_lock = threading.Lock()
        self._text_overlay: dict = self._load_text_overlay()
        self._text_overlay_lock = threading.Lock()
        self._yt_cache: dict     = {}   # {original_url: (resolved_url, monotonic_ts)}
        self._yt_resolving: dict = {}   # {original_url: asyncio.Task} — resolução em andamento
        self._yt_appended: dict  = {}   # {original_url: (hls_url, monotonic_ts)} — appendado na fila MPV
        self._vu_task: Optional[asyncio.Task] = None
        self._current_path: str = ""

    # ── Medição de nível de áudio via Windows Core Audio ────────────────────

    def _stop_vu(self):
        if self._vu_task and not self._vu_task.done():
            self._vu_task.cancel()
        self._vu_task = None

    async def _audio_level_task(self):
        """Lê o pico da saída de áudio padrão via IAudioMeterInformation e transmite.

        Chama get_peak_db() diretamente (sem executor): a chamada COM é sub-milissegundo
        e os objetos COM devem ser usados na thread onde foram criados (evento loop).
        """
        from . import win_audio_meter
        try:
            while True:
                await asyncio.sleep(0.08)
                db = win_audio_meter.get_peak_db()
                if db is not None:
                    await self._broadcast({"event": "audio_level", "db": db})
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("audio_level_task encerrada: %s", exc)
        finally:
            self._vu_task = None

    # ── Inicialização do MPV ──────────────────────────────────────────────────

    def _init_mpv(self):
        import mpv
        self._mpv_dead = False
        self._window_positioned = False
        _INPUT_CONF_PATH.write_text("CLOSE_WIN ignore\n", encoding="utf-8")

        geo = monitor.secondary_monitor_geometry()
        has_secondary = bool(geo)
        self._has_secondary = has_secondary

        mpv_kwargs = dict(
            ytdl=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            input_conf=str(_INPUT_CONF_PATH),
            video_sync="display-resample",
            hr_seek="yes",
            keep_open=False,
            idle=True,
            force_window="immediate",   # janela permanece aberta (tela preta) ao parar ou aguardar live
            title="PlayLine",
            log_handler=self._mpv_log,
            loglevel="warn",
            prefetch_playlist=True,
            volume_max=200,             # permite até +6 dB (200 = +6 dB)
            image_display_duration=86400,  # standby.png exibido por 24h (efetivamente infinito)
            hwdec="auto-safe",          # decodificação por GPU quando disponível, software como fallback
            osc=False,                  # desativa controles na tela ao passar o mouse
            network_timeout=10,         # desiste de stream morta em 10s (reduz freeze após queda de rede)
        )

        if has_secondary:
            mpv_kwargs.update(border=False, fullscreen=True, ontop=True, geometry=geo)
            logger.info("MPV geometry: %s", geo)
        else:
            mpv_kwargs.update(border=False, fullscreen=False, ontop=False, geometry="380x213")
            logger.warning(
                "Monitor secundário não detectado — MPV abrirá no principal em janela (380x213)"
            )

        self._mpv = mpv.MPV(**mpv_kwargs)
        self._mpv.volume = self._volume   # restaura volume ao reinicializar

        # Com force_window=immediate a janela abre antes de qualquer clipe;
        # posiciona no monitor correto logo ao inicializar.
        if has_secondary:
            threading.Thread(target=self._move_to_tv, daemon=True).start()
        else:
            threading.Thread(target=self._send_to_back, daemon=True).start()

        self._mpv.observe_property("time-pos", self._on_time_pos)
        try:
            self._mpv.observe_property("osd-width", self._on_osd_resize)
        except Exception as exc:
            logger.warning("observe_property(osd-width) indisponível: %s", exc)

        @self._mpv.event_callback("file-loaded")
        def _file_loaded(event):
            self._remove_standby_overlay()
            try:
                self._current_path = self._mpv.path or ""
            except Exception:
                pass
            if not self._window_positioned:
                target = self._move_to_tv if self._has_secondary else self._send_to_back
                threading.Thread(target=target, daemon=True).start()
            def _log_hwdec():
                import time
                time.sleep(0.5)
                if self._mpv_dead or self._mpv is None:
                    return
                try:
                    hwdec_active = self._mpv.hwdec_current
                    logger.info("Decodificação ativa: %s", hwdec_active or "software")
                except Exception:
                    pass
            threading.Thread(target=_log_hwdec, daemon=True).start()
            with self._logo_lock:
                has_active = any(d["active"] for d in self._logo.values())
            if has_active:
                threading.Thread(target=self._apply_overlay_delayed, daemon=True).start()
            with self._text_overlay_lock:
                text_active = self._text_overlay.get("active", False)
            if text_active:
                threading.Thread(target=self._apply_text_overlay_delayed, daemon=True).start()
            self._broadcast_sync({"event": "file-loaded"})

        @self._mpv.event_callback("end-file")
        def _end_file(event):
            if self._mpv_dead:
                return
            reason = protocol.parse_end_reason(event)
            logger.info("end-file reason=%s", reason)
            if reason != "stop":
                checkpoint.clear(CHECKPOINT_PATH)
            if reason in ("eof", "error") and _is_stream_path(self._current_path):
                threading.Thread(target=self._apply_standby_overlay, daemon=True).start()
            self._broadcast_sync({"event": "end-file", "reason": reason})

        @self._mpv.event_callback("shutdown")
        def _shutdown(event):
            if self._mpv_dead:
                return
            self._mpv_dead = True
            logger.info("MPV encerrado — reinit ocorrerá no próximo play")
            self._broadcast_sync({"event": "mpv_closed"})

        self._yt_appended.clear()
        logger.info("MPV inicializado")

    def _move_to_tv(self):
        monitor.move_window_to_secondary("PlayLine")
        self._window_positioned = True

    def _send_to_back(self):
        monitor.send_window_to_back("PlayLine")
        self._window_positioned = True

    def _mpv_log(self, level, component, message):
        logger.debug("[mpv/%s] %s", component, message.strip())

    # ── Callbacks de propriedade MPV ─────────────────────────────────────────

    def _on_time_pos(self, name, value):
        if value is not None and not self._mpv_dead:
            self._last_position = float(value)
            self._checkpoint_dirty = True

    def _on_osd_resize(self, name, value):
        """Re-aplica overlays (com debounce) quando a janela MPV é redimensionada."""
        if value is None:
            return
        with self._logo_lock:
            logos_active = any(d["active"] for d in self._logo.values())
        with self._text_overlay_lock:
            text_active = self._text_overlay.get("active", False)
        if not logos_active and not text_active:
            return
        if self._resize_scheduled:
            return
        self._resize_scheduled = True

        def _delayed():
            import time
            time.sleep(0.15)
            self._resize_scheduled = False
            if logos_active:
                self._apply_overlay()
            if text_active and self._mpv and not self._mpv_dead:
                with self._text_overlay_lock:
                    cfg = dict(self._text_overlay)
                osd_text.apply(self._mpv, cfg, None)

        threading.Thread(target=_delayed, daemon=True).start()

    # ── Logo overlay ─────────────────────────────────────────────────────────

    def _apply_overlay(self):
        with self._logo_lock:
            logo_snapshot = {k: dict(v) for k, v in self._logo.items()}
        overlay.apply(self._mpv, logo_snapshot, LOGOS_DIR)

    def _apply_overlay_delayed(self):
        import time
        time.sleep(0.5)
        if not self._mpv_dead:
            self._apply_overlay()

    def _apply_text_overlay_delayed(self):
        import time
        time.sleep(0.5)
        if self._mpv_dead or self._mpv is None:
            return
        with self._text_overlay_lock:
            cfg = dict(self._text_overlay)
        if cfg.get("active"):
            manual = cfg.get("manual_temp", "").strip()
            osd_text.apply(self._mpv, cfg, manual or None)

    # ── Standby overlay (problemastecnicos.png) ───────────────────────────────

    def _apply_standby_overlay(self):
        if not self._mpv or self._mpv_dead:
            return
        try:
            osd_w = int(self._mpv.osd_width  or self._mpv.width  or 1920)
            osd_h = int(self._mpv.osd_height or self._mpv.height or 1080)
        except Exception:
            osd_w, osd_h = 1920, 1080
        result = _render_standby_overlay(osd_w, osd_h)
        if result is None:
            return
        bgra_bytes, w, h = result
        tmp = Path(tempfile.gettempdir()) / "playline_standby.bgra"
        try:
            tmp.write_bytes(bgra_bytes)
        except Exception as exc:
            logger.error("[standby] erro ao gravar: %s", exc)
            return
        try:
            self._mpv.command(
                "overlay-add", STANDBY_SLOT, "0", "0",
                str(tmp), "0", "bgra", str(w), str(h), str(w * 4),
            )
            logger.info("[standby] overlay aplicado (%dx%d)", w, h)
        except Exception as exc:
            logger.warning("[standby] overlay-add falhou: %s", exc)

    def _remove_standby_overlay(self):
        if not self._mpv or self._mpv_dead:
            return
        try:
            self._mpv.command("overlay-remove", STANDBY_SLOT)
        except Exception:
            pass

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
            original_path = path
            start_time = cmd.get("start_time")
            end_time   = cmd.get("end_time")
            if not path:
                return
            if self._mpv_dead or self._mpv is None:
                logger.info("Reinicializando MPV para reprodução...")
                self._init_mpv()
            if self._mpv:
                if _is_youtube_url(path):
                    if cmd.get("force_resolve"):
                        self._yt_cache.pop(original_path, None)
                        logger.info("force_resolve: cache limpo para %s", original_path)
                    cached = self._yt_cache.get(original_path)
                    if cached and (time.monotonic() - cached[1]) < 14400:
                        path = cached[0]
                        logger.info("YouTube URL resolvida via cache: %s", original_path)
                    elif original_path in self._yt_resolving:
                        logger.info("Aguardando prefetch em andamento para: %s", original_path)
                        try:
                            path = await self._yt_resolving[original_path]
                        except Exception as exc:
                            logger.error("Prefetch falhou: %s", exc)
                            await self._broadcast({"event": "end-file", "reason": "error"})
                            return
                    else:
                        if cached:
                            del self._yt_cache[original_path]
                        task = asyncio.ensure_future(self._prefetch_yt_bg(original_path))
                        self._yt_resolving[original_path] = task
                        try:
                            t0 = time.monotonic()
                            path = await task
                            logger.info("YouTube stream resolvido em %.2fs: %s",
                                        time.monotonic() - t0, original_path)
                        except Exception as exc:
                            logger.error("Falha ao resolver YouTube URL: %s", exc)
                            await self._broadcast({"event": "end-file", "reason": "error"})
                            return
                    # Verifica se MPV já transitou automaticamente para o HLS appendado
                    appended = self._yt_appended.pop(original_path, None)
                    if appended and appended[0] == path and (time.monotonic() - appended[1]) < 300:
                        try:
                            cur = self._mpv.path
                        except Exception:
                            cur = None
                        if cur == path:
                            self._mpv.pause = False
                            self._write_checkpoint(original_path)
                            logger.info("play (MPV já em HLS, sem loadfile): %s", original_path)
                            self._stop_vu()
                            self._vu_task = asyncio.ensure_future(self._audio_level_task())
                            return
                opts_parts = []
                if not _is_youtube_url(original_path):
                    if start_time: opts_parts.append(f"start={start_time}")
                    if end_time:   opts_parts.append(f"end={end_time}")
                if opts_parts:
                    self._mpv.command("loadfile", path, "replace", 0, ",".join(opts_parts))
                else:
                    self._mpv.command("loadfile", path, "replace")
                self._mpv.pause = False
                self._write_checkpoint(original_path)
                logger.info("play: %s%s", original_path,
                            f" [trim {start_time}–{end_time}]" if opts_parts else "")
                self._stop_vu()
                if _is_youtube_url(original_path):
                    self._vu_task = asyncio.ensure_future(self._audio_level_task())

        elif action == "play_standby":
            threading.Thread(target=self._apply_standby_overlay, daemon=True).start()
            logger.info("[standby] overlay ativado via play_standby")

        elif action == "preload":
            path = cmd.get("path", "")
            if path and self._mpv and not self._mpv_dead:
                self._mpv.command("loadfile", path, "append")
                logger.info("preload: %s", path)

        elif action == "prefetch_yt":
            url = cmd.get("path", "")
            if url and _is_youtube_url(url):
                cached = self._yt_cache.get(url)
                already_fresh = cached and (time.monotonic() - cached[1]) < 14400
                if not already_fresh and url not in self._yt_resolving:
                    task = asyncio.ensure_future(self._prefetch_yt_bg(url))
                    self._yt_resolving[url] = task
                    logger.info("prefetch_yt solicitado: %s", url)

        elif action == "init_mpv":
            if self._mpv_dead or self._mpv is None:
                logger.info("Reinicializando MPV via init_mpv")
                self._init_mpv()
            await self._broadcast({"event": "mpv_ready"})

        elif action == "quit_mpv":
            if self._mpv and not self._mpv_dead:
                self._mpv_dead = True
                mpv_ref  = self._mpv
                self._mpv = None
                await self._broadcast({"event": "mpv_closed"})

                def _terminate():
                    try:
                        # terminate() chama mpv_terminate_destroy(), fechando a janela Win32
                        mpv_ref.terminate()
                        logger.info("MPV encerrado via terminate()")
                    except Exception as exc:
                        logger.warning("quit_mpv terminate: %s", exc)

                threading.Thread(target=_terminate, daemon=True).start()

        elif action == "pause":
            if self._mpv and not self._mpv_dead:
                self._mpv.pause = True

        elif action == "resume":
            if self._mpv and not self._mpv_dead:
                self._mpv.pause = False

        elif action == "stop":
            if self._mpv and not self._mpv_dead:
                self._stop_vu()
                self._mpv.command("stop")
                for slot in (1, 2, 3):
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
                with self._logo_lock:
                    self._logo[s]["corner"] = c
                    self._logo[s]["active"] = a
                    if f:
                        self._logo[s]["filename"] = f
                    logger.info("[set_logo] estado: %s", self._logo)
                self._apply_overlay()

            threading.Thread(target=_update, daemon=True).start()

        elif action == "set_volume":
            vol = max(0, min(200, int(cmd.get("volume", 100))))
            self._volume = float(vol)   # persiste para reaplicar no reinit
            if self._mpv and not self._mpv_dead:
                try:
                    self._mpv.volume = self._volume
                    logger.debug("volume → %.1f (%.1f dB)", vol, 20 * __import__("math").log10(max(vol, 0.001) / 100))
                except Exception as exc:
                    logger.warning("set_volume: %s", exc)

        elif action == "set_text_overlay":
            cfg = {
                "active":      bool(cmd.get("active",    False)),
                "show_time":   bool(cmd.get("show_time", True)),
                "show_temp":   bool(cmd.get("show_temp", True)),
                "corner":      str(cmd.get("corner",    "tl")),
                "city":        str(cmd.get("city",      "Palmas,TO")),
                "manual_temp": str(cmd.get("manual_temp", "")),
            }
            with self._text_overlay_lock:
                self._text_overlay.update(cfg)
            self._save_text_overlay()
            if not cfg["active"] and self._mpv and not self._mpv_dead:
                osd_text.remove(self._mpv)
            self._broadcast_sync({"event": "text_overlay_state", **cfg})

        elif action == "get_text_overlay":
            with self._text_overlay_lock:
                cfg = dict(self._text_overlay)
            resp = {"event": "text_overlay_state", **cfg}
            try:
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
            except Exception:
                pass

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

    # ── Text overlay (hora + temperatura) ────────────────────────────────────

    def _load_text_overlay(self) -> dict:
        try:
            data = json.loads(TEXT_OVERLAY_PATH.read_text(encoding="utf-8"))
            result = {**_TEXT_OVERLAY_DEFAULTS, **data}
            if result.get("city") == "Palmas":
                result["city"] = "Palmas,TO"
            return result
        except Exception:
            return dict(_TEXT_OVERLAY_DEFAULTS)

    def _save_text_overlay(self) -> None:
        try:
            with self._text_overlay_lock:
                data = dict(self._text_overlay)
            TEXT_OVERLAY_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("[text_overlay] falha ao salvar: %s", exc)

    # ── Tarefas assíncronas ───────────────────────────────────────────────────

    def _try_append_hls(self, original_url: str, hls_url: str):
        """Appenda HLS na fila do MPV para pré-bufferizar enquanto o clipe atual toca."""
        if not self._mpv or self._mpv_dead:
            return
        try:
            current = self._mpv.path
        except Exception:
            return
        if current is None:
            return
        # Não appenda se MPV já está em live (evita live→live com append desnecessário)
        if "googlevideo" in current or _is_youtube_url(current):
            return
        self._mpv.command("loadfile", hls_url, "append")
        self._yt_appended[original_url] = (hls_url, time.monotonic())
        logger.info("HLS appendado para pré-bufferização: %s", original_url)

    async def _prefetch_yt_bg(self, url: str) -> str:
        try:
            t0 = time.monotonic()
            resolved = await asyncio.get_event_loop().run_in_executor(
                None, _resolve_yt_stream, url
            )
            elapsed = time.monotonic() - t0
            self._yt_cache[url] = (resolved, time.monotonic())
            logger.info("YouTube URL pré-resolvida em %.2fs: %s", elapsed, url)
            self._try_append_hls(url, resolved)
            return resolved
        except Exception as exc:
            logger.warning("Falha no prefetch de YouTube URL: %s", exc)
            raise
        finally:
            self._yt_resolving.pop(url, None)

    async def _checkpoint_task(self):
        # Primeiros dois flushes em 1s e 2s para cobrir crashes logo no início do clipe
        for early in (1, 2):
            await asyncio.sleep(early)
            self._flush_checkpoint()
        while True:
            await asyncio.sleep(5)
            self._flush_checkpoint()

    async def _text_overlay_task(self):
        while True:
            await asyncio.sleep(1)
            if self._mpv_dead or self._mpv is None:
                continue
            with self._text_overlay_lock:
                cfg = dict(self._text_overlay)
            if not cfg.get("active"):
                continue
            temp = None
            if cfg.get("show_temp"):
                manual = cfg.get("manual_temp", "").strip()
                if manual:
                    temp = manual
                else:
                    try:
                        temp = await weather.get_temperature(cfg.get("city", "Palmas,TO"))
                    except Exception:
                        pass
            osd_text.apply(self._mpv, cfg, temp)

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

    async def _preview_task(self):
        """Captura frames MPV a ~10 fps e distribui para clientes TCP conectados."""
        import base64
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(0.05)   # alvo 20 fps (limitado pelo tempo de captura)
            if self._mpv_dead or self._mpv is None or not self._clients:
                continue
            try:
                if self._mpv.path is None:
                    continue
            except Exception:
                continue
            mpv_ref = self._mpv
            jpeg = await loop.run_in_executor(None, preview.capture_jpeg, mpv_ref)
            if jpeg and self._clients:
                b64 = base64.b64encode(jpeg).decode("ascii")
                await self._broadcast({"event": "preview_frame", "data": b64})

    async def serve(self):
        self._loop = asyncio.get_event_loop()
        self._init_mpv()
        server = await asyncio.start_server(self.handle_client, HOST, PORT)
        logger.info("MPV Daemon escutando em %s:%d — PID %d", HOST, PORT, os.getpid())
        asyncio.create_task(self._checkpoint_task())
        asyncio.create_task(self._position_task())
        asyncio.create_task(self._text_overlay_task())
        asyncio.create_task(self._preview_task())
        async with server:
            await server.serve_forever()


# ── Utilitário ────────────────────────────────────────────────────────────────

def _list_logos(logos_dir: Path) -> list[str]:
    return sorted(
        f.name for f in logos_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg")
    )
