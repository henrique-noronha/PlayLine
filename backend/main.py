"""Ponto de entrada do PlayLine — inicialização do FastAPI e wiring dos módulos."""

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from core.player import Player
from core.playlist import PlaylistEngine
from api.routes import router as http_router, setup as setup_routes, prewarm_thumbnails
from api.auth import (
    router as auth_router, SessionAuth, session_valid, SESSIONS, save_sessions,
    SESSION_TTL, _brand_logo_file,
)
from api.websocket import router as ws_router, setup as setup_ws, ws_authorized
from core.db import init_db, migrate_from_json
from core import settings as app_settings

_log_handlers = [logging.StreamHandler()]
if getattr(sys, "frozen", False):
    _log_file = Path(sys.executable).parent / "playline.log"
    _log_handlers.append(logging.FileHandler(_log_file, encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend"
    _DATA_DIR    = Path(sys.executable).parent
else:
    FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
    _DATA_DIR    = Path(__file__).parent

class ConnectionManager:
    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)
        logger.info("WS conectado — total: %d", len(self._clients))

    def disconnect(self, ws: WebSocket):
        if ws in self._clients:
            self._clients.remove(ws)
        logger.info("WS desconectado — total: %d", len(self._clients))

    async def broadcast(self, data: dict):
        payload = json.dumps(data, ensure_ascii=False)
        dead = []
        for client in self._clients:
            try:
                await client.send_text(payload)
            except Exception:
                dead.append(client)
        for c in dead:
            self._clients.remove(c)


class PreviewManager:
    """Distribui frames JPEG (binário) para clientes /ws/preview."""

    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        logger.info("Preview WS conectado — total: %d", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._clients:
            self._clients.remove(ws)
        logger.info("Preview WS desconectado — total: %d", len(self._clients))

    async def broadcast(self, data: bytes) -> None:
        dead = []
        for client in self._clients:
            try:
                await client.send_bytes(data)
            except Exception:
                dead.append(client)
        for c in dead:
            if c in self._clients:
                self._clients.remove(c)

    @property
    def count(self) -> int:
        return len(self._clients)

manager = ConnectionManager()
preview_manager = PreviewManager()
playlist_engine: PlaylistEngine | None = None
player_instance: Player | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global playlist_engine, player_instance
    loop = asyncio.get_event_loop()

    def _on_end(reason: str):
        if playlist_engine:
            playlist_engine.on_end_file(reason)

    def _on_position(pos: float):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"event": "position", "pos": pos}),
            loop,
        )
        if playlist_engine:
            playlist_engine.on_position(pos)

    def _on_logo_list(files: list):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"event": "logo_list", "files": files}),
            loop,
        )

    def _on_logo_state(msg: dict):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast(msg),
            loop,
        )

    def _on_audio_level(db):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"event": "audio_level", "db": db}),
            loop,
        )

    def _on_text_overlay_state(state: dict):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast(state),
            loop,
        )

    def _on_preview_frame(b64: str):
        if preview_manager.count == 0:
            return
        try:
            import base64
            data = base64.b64decode(b64)
        except Exception:
            return
        asyncio.run_coroutine_threadsafe(preview_manager.broadcast(data), loop)

    def _on_file_loaded():
        if playlist_engine:
            playlist_engine.on_file_loaded()

    init_db()
    migrate_from_json(_DATA_DIR)

    player_instance = Player(
        on_end_file=_on_end,
        on_position=_on_position,
        on_logo_list=_on_logo_list,
        on_logo_state=_on_logo_state,
        on_text_overlay_state=_on_text_overlay_state,
        on_preview_frame=_on_preview_frame,
        on_file_loaded=_on_file_loaded,
        on_audio_level=_on_audio_level,
    )
    playlist_engine = PlaylistEngine(player=player_instance, broadcast=manager.broadcast)
    playlist_engine.set_event_loop(loop)
    playlist_engine.load_schedule()

    setup_routes(playlist_engine, manager)
    setup_ws(playlist_engine, manager, session_valid)

    await loop.run_in_executor(None, playlist_engine.restore_after_crash)

    asyncio.create_task(prewarm_thumbnails())

    logger.info("Sistema de playout iniciado")
    yield

    if player_instance:
        player_instance.shutdown()
    logger.info("Sistema encerrado")



class _RevalidatingStaticFiles(StaticFiles):
    """Arquivos do frontend com revalidação (no-cache)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="PlayLine", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.add_middleware(SessionAuth)
app.mount("/static", _RevalidatingStaticFiles(directory=str(FRONTEND_DIR)), name="static")
app.include_router(http_router)
app.include_router(auth_router)
app.include_router(ws_router)


@app.websocket("/ws/preview")
async def preview_ws(ws: WebSocket):
    if not await ws_authorized(ws):
        return
    await preview_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()   # mantém vivo; dados fluem apenas servidor→cliente
    except Exception:
        preview_manager.disconnect(ws)


@app.get("/api/ping")
async def ping():
    return {"playline": True}


_LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")


def _is_local(request: Request) -> bool:
    return bool(request.client) and request.client.host in _LOCAL_HOSTS


def _setup_blocked(request: Request) -> Optional[JSONResponse]:
    if app_settings.is_setup_done():
        return JSONResponse({"detail": "Configuração inicial já concluída", "code": "setup_done"},
                            status_code=409)
    if not _is_local(request):
        return JSONResponse({"detail": "Conclua a configuração inicial no computador do PlayLine",
                             "code": "setup_local_only"}, status_code=403)
    return None


_SETUP_REMOTE_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PlayLine</title>
<style>body{{background:#0f1117;color:#e2e8f0;font-family:'Segoe UI',system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
p{{max-width:420px;line-height:1.6;color:#94a3b8}}h1{{font-size:20px;margin-bottom:10px}}</style>
</head><body><div><h1 id="h">PlayLine</h1><p id="m"></p></div><script>
var M={{pt:"A configuração inicial do PlayLine ainda não foi concluída. Conclua-a no computador onde o PlayLine está instalado.",
en:"PlayLine's initial setup has not been completed yet. Complete it on the computer where PlayLine is installed.",
es:"La configuración inicial de PlayLine aún no se ha completado. Complétela en el equipo donde está instalado PlayLine."}};
var l="{lang}";try{{var v=localStorage.getItem("playline_lang");if(M[v])l=v;}}catch(e){{}}
document.getElementById("m").textContent=M[l]||M.en;</script></body></html>"""


@app.get("/setup")
async def setup_page(request: Request):
    if app_settings.is_setup_done():
        return RedirectResponse(url="/", status_code=302)
    if not _is_local(request):
        return HTMLResponse(_SETUP_REMOTE_HTML.format(lang=app_settings.get_language()), status_code=403)
    html = (FRONTEND_DIR / "setup" / "setup.html").read_text(encoding="utf-8")
    return HTMLResponse(_with_asset_version(html), headers={"Cache-Control": "no-store"})


@app.get("/setup/logo")
async def setup_logo():
    lp = _brand_logo_file()
    if not lp:
        return Response(status_code=404)
    return FileResponse(str(lp), media_type="image/png")


@app.get("/api/setup/state")
async def setup_state(request: Request):
    """Valores atuais para pré-preencher o assistente (quem atualiza já tem os seus)."""
    blocked = _setup_blocked(request)
    if blocked:
        return blocked
    from api import library_routes as _lib
    cfg_lib = app_settings.get_library_dir()
    raw_lang = app_settings.load().get("language")
    return {
        "language": raw_lang if raw_lang in app_settings.LANGUAGES else None,
        "username": app_settings.get_username(),
        "library_dir": str(_lib._LIBRARY_BASE),
        "library_default": str(_lib._LIBRARY_DEFAULT),
        "library_custom": cfg_lib is not None,
        "password_min": app_settings.PASSWORD_MIN,
    }


@app.post("/api/setup/complete")
async def setup_complete(request: Request):
    """Aplica as três etapas de uma vez, abre a sessão e marca a configuração como concluída."""
    blocked = _setup_blocked(request)
    if blocked:
        return blocked
    try:
        body = await request.json()
    except Exception:
        body = {}
    loop = asyncio.get_running_loop()

    def _err(step: str, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": getattr(exc, "code", "invalid_value"),
                             "params": getattr(exc, "params", {}), "step": step}, status_code=400)

    lang = body.get("language")
    if lang not in app_settings.LANGUAGES:
        return _err("language", app_settings.SettingsError("language_invalid", "Idioma inválido"))

    creds = body.get("credentials")
    if creds is not None:
        if not isinstance(creds, dict):
            return _err("credentials", app_settings.SettingsError("invalid_value", "Credenciais inválidas"))
        try:
            app_settings.validate_new_credentials(creds.get("username"), creds.get("password"))
        except ValueError as exc:
            return _err("credentials", exc)

    lib_reset = body.get("library_reset") is True   # volta à pasta padrão
    lib_path = None if lib_reset else body.get("library_path")   # None = manter a pasta em uso
    if lib_path is not None:
        try:
            await loop.run_in_executor(None, app_settings.validate_library_dir, str(lib_path))
        except ValueError as exc:
            return _err("library", exc)

    app_settings.set_language(lang)
    if creds is not None:
        await loop.run_in_executor(
            None, app_settings.set_credentials, creds.get("username"), creds.get("password"))
        SESSIONS.clear()
    if lib_reset or lib_path is not None:
        from api import library_routes as _lib
        resp = await _lib.change_library_dir({"reset": True} if lib_reset else {"path": lib_path})
        if isinstance(resp, Response):
            return resp
    app_settings.mark_setup_done()

    token = secrets.token_urlsafe(32)
    SESSIONS[token] = time.time() + SESSION_TTL
    save_sessions(SESSIONS)
    logger.info("Configuração inicial concluída (idioma=%s, credenciais %s, biblioteca %s)",
                lang, "alteradas" if creds is not None else "mantidas",
                "padrão" if lib_reset else ("alterada" if lib_path is not None else "mantida"))
    resp = JSONResponse({"ok": True})
    resp.set_cookie("playline_session", token, httponly=True, samesite="lax", max_age=SESSION_TTL)
    return resp


_LANG_MARKER = '<script src="/static/i18n/pt.js"></script>'


def _frontend_version() -> str:
    """Muda sempre que algum arquivo do frontend muda (maior mtime, em hexadecimal)."""
    try:
        newest = max(f.stat().st_mtime for f in FRONTEND_DIR.rglob("*") if f.is_file())
    except (OSError, ValueError):
        newest = time.time()
    return format(int(newest), "x")


_ASSET_VERSION = _frontend_version()
_ASSET_RE = re.compile(r'((?:src|href)="/static/[^"?]+)"')


def _with_asset_version(html: str) -> str:
    """Acrescenta ?v=<versão> nas referências a /static/ das páginas HTML."""
    return _ASSET_RE.sub(rf'\1?v={_ASSET_VERSION}"', html)


@app.get("/")
async def index():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    lang = json.dumps(app_settings.get_language())
    html = html.replace(_LANG_MARKER,
                        f"<script>window.PLAYLINE_SERVER_LANG = {lang};</script>\n  {_LANG_MARKER}", 1)
    return HTMLResponse(_with_asset_version(html), headers={"Cache-Control": "no-cache"})


def _run_server(port: int = 18000):
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
        log_config=None,
    )


_SPLASH_MIN_SECONDS = 4


def _get_autostart_token() -> Optional[str]:
    """Lê o token válido mais recente direto do disco para auto-login na reabertura."""
    from api.auth import _SESSIONS_FILE
    try:
        if not _SESSIONS_FILE.exists():
            logger.info("Auto-login: sessions.json não encontrado em %s", _SESSIONS_FILE)
            return None
        data = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
        now = time.time()
        tok = next((t for t, exp in data.items() if isinstance(exp, (int, float)) and exp > now), None)
        logger.info("Auto-login: %d sessões no arquivo, token válido: %s", len(data), bool(tok))
        return tok
    except Exception as exc:
        logger.warning("Auto-login: erro ao ler sessions.json: %s", exc)
        return None


def _wait_and_navigate(window, port: int = 18000):
    import socket
    start = time.time()
    server_ready = False
    for _ in range(60):
        time.sleep(0.5)
        if not server_ready:
            try:
                s = socket.create_connection(("localhost", port), timeout=1)
                s.close()
                server_ready = True
            except Exception:
                pass
        if server_ready and (time.time() - start) >= _SPLASH_MIN_SECONDS:
            _tok = _get_autostart_token()
            _url = f"http://localhost:{port}/?session_token={_tok}" if _tok else f"http://localhost:{port}"
            logger.info("Navegando para: %s", _url[:80])
            window.load_url(_url)
            return


if __name__ == "__main__":
    if '--server-only' in sys.argv:
        try:
            _srv_port = int(sys.argv[sys.argv.index('--port') + 1])
        except (ValueError, IndexError):
            _srv_port = 18000
        (_DATA_DIR / "server.pid").write_text(str(os.getpid()), encoding="utf-8")
        try:
            _run_server(_srv_port)
        finally:
            try:
                (_DATA_DIR / "server.pid").unlink()
            except Exception:
                pass
        sys.exit(0)

    def _unblock_meipass():
        if not getattr(sys, 'frozen', False):
            return
        import ctypes
        k32 = ctypes.windll.kernel32
        for base in (Path(sys._MEIPASS), Path(sys.executable).parent):
            try:
                for f in base.rglob('*'):
                    if f.is_file():
                        k32.DeleteFileW(str(f) + ':Zone.Identifier')
            except Exception:
                pass

    _unblock_meipass()

    def _set_gpu_preference():
        """Garante GPU de alto desempenho para o daemon MPV via registro do Windows."""
        try:
            import winreg
            key_path = r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences"
            base = Path(sys.executable).parent
            targets = [
                base / "PlayLine-daemon.exe",
                Path(sys.executable),
            ]
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, key_path, 0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            ) as key:
                for exe in targets:
                    if not exe.exists():
                        continue
                    exe_str = str(exe)
                    try:
                        current, _ = winreg.QueryValueEx(key, exe_str)
                        if "GpuPreference=2" in current:
                            logger.info("GPU de alto desempenho já configurada para: %s", exe_str)
                            continue
                    except FileNotFoundError:
                        pass
                    winreg.SetValueEx(key, exe_str, 0, winreg.REG_SZ, "GpuPreference=2;")
                    logger.info("GPU de alto desempenho configurada (novo): %s", exe_str)
        except Exception as exc:
            logger.warning("Não foi possível configurar preferência de GPU: %s", exc)

    _set_gpu_preference()

    import webview

    def _check_dependencies():
        import ctypes, subprocess, tempfile, urllib.request, winreg
        from pathlib import Path as _Path

        MB_OK, MB_OKCANCEL = 0x00, 0x01
        MB_ICONERROR, MB_ICONWARN, MB_ICONINFO = 0x10, 0x30, 0x40
        IDOK = 1

        def _msgbox(msg, title="PlayLine", style=MB_OK | MB_ICONINFO):
            return ctypes.windll.user32.MessageBoxW(0, msg, title, style)

        def _is_admin():
            try:
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False

        def _dotnet_ok():
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
                )
                val, _ = winreg.QueryValueEx(key, "Release")
                winreg.CloseKey(key)
                return val >= 528040  # .NET 4.8+
            except Exception:
                return False

        def _webview2_ok():
            guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for sub in (
                    rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}",
                    rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}",
                ):
                    try:
                        winreg.OpenKey(hive, sub)
                        return True
                    except Exception:
                        pass
            return False

        missing = []
        if not _dotnet_ok():
            missing.append((
                ".NET Framework 4.8",
                "https://go.microsoft.com/fwlink/?LinkId=2085155",
                "ndp48-web.exe",
                ["/passive", "/norestart"],
            ))
        if not _webview2_ok():
            missing.append((
                "WebView2 Runtime",
                "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
                "webview2setup.exe",
                ["/silent", "/install"],
            ))

        if not missing:
            return

        if not _is_admin():
            _msgbox(
                "O PlayLine precisa instalar componentes obrigatórios da Microsoft.\n\n"
                "Clique em OK para continuar — o Windows pedirá permissão de administrador.",
                "PlayLine — Permissão necessária",
                MB_OK | MB_ICONWARN,
            )
            params = " ".join(f'"{a}"' for a in sys.argv)
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            sys.exit(0)

        names = "\n".join(f"• {n}" for n, *_ in missing)
        res = _msgbox(
            f"O PlayLine precisa dos seguintes componentes para funcionar:\n\n{names}"
            f"\n\nTodos são gratuitos e fornecidos pela Microsoft."
            f"\n\nClique em OK para instalar automaticamente agora.",
            "PlayLine — Instalação necessária",
            MB_OKCANCEL | MB_ICONWARN,
        )
        if res != IDOK:
            sys.exit(0)

        tmp = _Path(tempfile.gettempdir())
        errors = []
        needs_reboot = False

        for name, url, fname, flags in missing:
            dest = tmp / fname
            try:
                urllib.request.urlretrieve(url, dest)
                proc = subprocess.run([str(dest)] + flags)
                if proc.returncode in (1641, 3010):
                    needs_reboot = True
                elif proc.returncode != 0:
                    errors.append(f"{name}: código {proc.returncode}")
            except Exception as e:
                errors.append(f"{name}: {e}")

        if errors:
            _msgbox(
                "Ocorreu um erro durante a instalação:\n\n" + "\n".join(errors)
                + "\n\nTente instalar manualmente pelo site da Microsoft.",
                "PlayLine — Erro na instalação",
                MB_OK | MB_ICONERROR,
            )
            sys.exit(1)

        if needs_reboot:
            _msgbox(
                "Instalação concluída!\n\nReinicie o Windows para finalizar a instalação do .NET Framework"
                " e depois abra o PlayLine novamente.",
                "PlayLine — Reinicialização necessária",
                MB_OK | MB_ICONINFO,
            )
            sys.exit(0)

        _msgbox(
            "Instalação concluída!\n\nAbra o PlayLine novamente para usar.",
            "PlayLine",
            MB_OK | MB_ICONINFO,
        )
        sys.exit(0)

    _check_dependencies()

    if getattr(sys, "frozen", False):
        _base = Path(sys.executable).parent
    else:
        _base = Path(__file__).parent

    _logo_html = "<div style=\"font-size:32px;font-weight:700;color:#e5e7eb\">PlayLine</div>"
    for _name in ("LogoPlayLineD.png", "FavPlayline.png"):
        _lp = _base / "logos" / _name
        if _lp.exists():
            _b64 = base64.b64encode(_lp.read_bytes()).decode()
            _logo_html = f'<img src="data:image/png;base64,{_b64}" style="max-width:280px;max-height:140px;object-fit:contain" />'
            break

    _splash = f"""<!DOCTYPE html><html><head><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#111827;display:flex;flex-direction:column;align-items:center;
  justify-content:center;height:100vh;gap:28px;
  font-family:'Segoe UI',system-ui,sans-serif}}
.loader{{display:flex;gap:10px;align-items:center}}
.dot{{width:10px;height:10px;border-radius:50%;background:#4f8ef7;
  box-shadow:0 0 8px rgba(79,142,247,.5);animation:wave 1.4s ease infinite}}
.dot:nth-child(1){{animation-delay:0s}}
.dot:nth-child(2){{animation-delay:.18s}}
.dot:nth-child(3){{animation-delay:.36s}}
.dot:nth-child(4){{animation-delay:.54s}}
@keyframes wave{{0%,100%{{transform:translateY(0);opacity:1}}50%{{transform:translateY(-10px);opacity:.3}}}}
.lbl{{font-size:11px;color:#4b5563;letter-spacing:.1em;text-transform:uppercase}}
.credits{{position:fixed;bottom:18px;left:0;right:0;text-align:center;
  font-size:10px;color:#374151;letter-spacing:.06em}}
</style></head><body>
{_logo_html}
<div class="loader">
  <div class="dot"></div><div class="dot"></div>
  <div class="dot"></div><div class="dot"></div>
</div>
<span class="lbl">Iniciando servidor…</span>
<span class="credits">Desenvolvido por Henrique Noronha Fernandes</span>
</body></html>"""

    def _check_playline_running(port: int) -> bool:
        import urllib.request, json
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/api/ping", timeout=1) as r:
                return json.loads(r.read()).get("playline") is True
        except Exception:
            return False

    def _find_free_port(start: int = 18000) -> int:
        import socket
        for port in range(start, start + 100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("0.0.0.0", port))
                    return port
            except OSError:
                continue
        return start

    def _center(win_w: int, win_h: int) -> tuple[int, int]:
        try:
            import ctypes
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            return max(0, (sw - win_w) // 2), max(0, (sh - win_h) // 2)
        except Exception:
            return 0, 0

    _WIN_W, _WIN_H = 1440, 860
    _cx, _cy = _center(_WIN_W, _WIN_H)

    def _is_remote_session() -> bool:
        """Detecta sessão RDP/remota — SM_REMOTESESSION = 0x1000."""
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))
        except Exception:
            return False

    _closing_confirmed = False  # True quando o fechamento é intencional (via API)

    class _PyWebViewAPI:
        """Métodos Python expostos ao JavaScript via window.pywebview.api.*"""
        def pick_folder(self, start_dir: str = "") -> str:
            """Diálogo nativo de pasta (Configurações > Biblioteca)."""
            if not _window:
                return ""
            try:
                kwargs = {"directory": start_dir} if start_dir and os.path.isdir(start_dir) else {}
                res = _window.create_file_dialog(webview.FOLDER_DIALOG, **kwargs)
            except Exception as exc:
                logger.warning("pick_folder falhou: %s", exc)
                return ""
            if not res:
                return ""
            return str(res[0]) if isinstance(res, (list, tuple)) else str(res)

        def close_interface_only(self):
            """Fecha a janela; daemon e servidor continuam rodando."""
            global _closing_confirmed
            _closing_confirmed = True
            if _window:
                _window.destroy()

        def close_all(self):
            """Para o player, encerra o processo do daemon e fecha a janela PyWebView."""
            global _closing_confirmed
            try:
                import asyncio
                import api.routes as _routes
                eng = _routes._playlist_engine
                if eng and eng._loop and eng._loop.is_running():
                    asyncio.run_coroutine_threadsafe(eng.stop(), eng._loop)
            except Exception:
                pass
            try:
                import subprocess as _sp
                r = _sp.run(
                    ['netstat', '-ano'],
                    capture_output=True, text=True, timeout=5,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
                for line in r.stdout.splitlines():
                    if ':6600' in line and 'LISTENING' in line:
                        pid = int(line.strip().split()[-1])
                        _sp.run(
                            ['taskkill', '/F', '/PID', str(pid)],
                            capture_output=True, timeout=5,
                            creationflags=0x08000000,
                        )
                        break
            except Exception:
                pass
            try:
                import subprocess as _sp
                _pid_file = _DATA_DIR / "server.pid"
                if _pid_file.exists():
                    _srv_pid = int(_pid_file.read_text(encoding="utf-8").strip())
                    _sp.run(
                        ['taskkill', '/F', '/PID', str(_srv_pid)],
                        capture_output=True, timeout=5,
                        creationflags=0x08000000,
                    )
                    try:
                        _pid_file.unlink()
                    except Exception:
                        pass
            except Exception:
                pass
            SESSIONS.clear()
            save_sessions(SESSIONS)
            _closing_confirmed = True
            if _window:
                _window.destroy()

    _pywebview_api = _PyWebViewAPI()
    _window = None  # preenchido abaixo

    def _on_closing():
        """Intercepta o botão X da janela."""
        if _closing_confirmed or _is_remote_session():
            return  # permite fechar normalmente
        def _deferred():
            time.sleep(0.05)
            if _window:
                try:
                    _window.evaluate_js(
                        "if (typeof window._showCloseDialog !== 'undefined') {"
                        "  window._showCloseDialog();"
                        "} else {"
                        "  window.pywebview.api.close_all();"
                        "}"
                    )
                except Exception:
                    pass
        threading.Thread(target=_deferred, daemon=True).start()
        return False  # cancela o fechamento padrão

    def _start_webview(func=None):
        import ctypes
        try:
            if func:
                webview.start(func, private_mode=False)
            else:
                webview.start(private_mode=False)
        except Exception as e:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Não foi possível iniciar a interface do PlayLine.\n\n"
                "Verifique se .NET Framework 4.8 e WebView2 Runtime estão instalados.\n\n"
                f"Detalhe: {type(e).__name__}: {e}",
                "PlayLine — Erro de inicialização",
                0x10,
            )
            sys.exit(1)

    import subprocess as _sp_srv

    def _server_cmd(port: int) -> list[str]:
        return (
            [sys.executable, '--server-only', '--port', str(port)]
            if getattr(sys, 'frozen', False) else
            [sys.executable, str(Path(__file__).resolve()), '--server-only', '--port', str(port)]
        )

    def _spawn_server(port: int) -> None:
        _sp_srv.Popen(
            _server_cmd(port),
            creationflags=_sp_srv.DETACHED_PROCESS | _sp_srv.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )

    _SUPERVISE_SEC  = 10   # intervalo do ping de saúde
    _SUPERVISE_MISS = 3    # relança após esse nº de pings falhos seguidos (~30 s)

    def _supervise_server(port: int) -> None:
        """Relanca o servidor se ele morrer enquanto a janela estiver aberta."""
        misses = 0
        while not _closing_confirmed:
            time.sleep(_SUPERVISE_SEC)
            if _closing_confirmed:
                return
            if _check_playline_running(port):
                misses = 0
                continue
            misses += 1
            if misses >= _SUPERVISE_MISS:
                logger.error("Servidor sem resposta há ~%ds — relançando", _SUPERVISE_SEC * misses)
                misses = 0
                try:
                    _spawn_server(port)
                except Exception as exc:
                    logger.error("Falha ao relançar o servidor: %s", exc)

    if _check_playline_running(18000):
        _PORT = 18000
        _tok = _get_autostart_token()
        _start_url = f"http://localhost:{_PORT}/?session_token={_tok}" if _tok else f"http://localhost:{_PORT}"
        _window = webview.create_window(
            "PlayLine",
            _start_url,
            width=_WIN_W,
            height=_WIN_H,
            x=_cx,
            y=_cy,
            min_size=(960, 600),
            js_api=_pywebview_api,
        )
        _window.events.closing += _on_closing
        threading.Thread(target=_supervise_server, args=(_PORT,), daemon=True).start()
        _start_webview()
    else:
        _PORT = _find_free_port(18000)
        _spawn_server(_PORT)
        _window = webview.create_window(
            "PlayLine",
            html=_splash,
            width=_WIN_W,
            height=_WIN_H,
            x=_cx,
            y=_cy,
            min_size=(960, 600),
            js_api=_pywebview_api,
        )
        _window.events.closing += _on_closing
        threading.Thread(target=_supervise_server, args=(_PORT,), daemon=True).start()
        _start_webview(
            lambda: threading.Thread(target=_wait_and_navigate, args=(_window, _PORT), daemon=True).start()
        )
