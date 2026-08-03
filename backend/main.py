"""Ponto de entrada do PlayLine — inicialização do FastAPI e wiring dos módulos."""

import asyncio
import base64
import json
import logging
import os
import secrets
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from core.player import Player
from core.playlist import PlaylistEngine
from api.routes import router as http_router, setup as setup_routes, prewarm_thumbnails
from api.websocket import router as ws_router, setup as setup_ws
from core.db import init_db, migrate_from_json

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


# Gerenciadores de conexões WebSocket

class ConnectionManager:
    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)
        logger.info("WS conectado — total: %d", len(self._clients))

    def disconnect(self, ws: WebSocket):
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


# Lifecycle                                                            #

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

    def _on_file_loaded():
        if playlist_engine:
            playlist_engine.on_file_loaded()

    def _on_position(pos: float):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"event": "position", "pos": pos}),
            loop,
        )

    def _on_logo_list(files: list):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"event": "logo_list", "files": files}),
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

    init_db()
    migrate_from_json(_DATA_DIR)

    player_instance = Player(
        on_end_file=_on_end,
        on_position=_on_position,
        on_logo_list=_on_logo_list,
        on_text_overlay_state=_on_text_overlay_state,
        on_preview_frame=_on_preview_frame,
        on_file_loaded=_on_file_loaded,
    )
    playlist_engine = PlaylistEngine(player=player_instance, broadcast=manager.broadcast)
    playlist_engine.set_event_loop(loop)
    playlist_engine.load_schedule()

    setup_routes(playlist_engine, manager)
    setup_ws(playlist_engine, manager)

    # Detecta se o daemon já estava reproduzindo algo (crash/reinício do servidor)
    await loop.run_in_executor(None, playlist_engine.restore_after_crash)

    # Pré-aquece cache de thumbnails em background (aproveita o tempo da splash + login)
    asyncio.create_task(prewarm_thumbnails())

    logger.info("Sistema de playout iniciado")
    yield

    if player_instance:
        player_instance.shutdown()
    logger.info("Sistema encerrado")


# App                                                                  #

_AUTH_USER = os.environ.get("PLAYLINE_USER", "playline")
_AUTH_PASS = os.environ.get("PLAYLINE_PASS", "playline")
_SESSIONS: set[str] = set()


def _build_login_html(error: bool = False) -> str:
    if getattr(sys, "frozen", False):
        logos_dir = Path(sys.executable).parent / "logos"
    else:
        logos_dir = Path(__file__).parent / "logos"

    logo_tag = "<span style='font-size:26px;font-weight:700;color:#e5e7eb'>PlayLine</span>"
    for name in ("LogoPlayLineD.png", "FavPlayline.png"):
        lp = logos_dir / name
        if lp.exists():
            b64 = base64.b64encode(lp.read_bytes()).decode()
            logo_tag = f'<img src="data:image/png;base64,{b64}" style="max-width:280px;max-height:140px;object-fit:contain" alt="PlayLine" />'
            break

    error_html = """<p style="color:#ef4444;font-size:12px;text-align:center;margin-top:4px">
        Usuário ou senha incorretos.</p>""" if error else ""

    return f"""<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlayLine — Autenticação</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#111827;display:flex;flex-direction:column;align-items:center;
  justify-content:center;height:100vh;gap:32px;
  font-family:'Segoe UI',system-ui,sans-serif;color:#e5e7eb}}
.logo-wrap{{display:flex;flex-direction:column;align-items:center;gap:12px}}
.subtitle{{font-size:12px;color:#6b7280;letter-spacing:.08em;text-transform:uppercase;font-weight:500}}
form{{display:flex;flex-direction:column;gap:12px;width:280px}}
.field{{display:flex;flex-direction:column;gap:5px}}
label{{font-size:11px;color:#4b5563;font-weight:600;letter-spacing:.06em;text-transform:uppercase}}
input{{background:#1a2332;border:1px solid #2d3748;border-radius:8px;color:#e5e7eb;
  font-size:14px;padding:10px 13px;outline:none;transition:border-color .15s;width:100%;
  font-family:'Segoe UI',system-ui,sans-serif}}
input:focus{{border-color:#4f8ef7;background:#1e2a40}}
button{{background:#4f8ef7;border:none;border-radius:8px;color:#fff;cursor:pointer;
  font-size:13px;font-weight:600;padding:11px;width:100%;margin-top:4px;
  transition:background .15s;letter-spacing:.02em}}
button:hover{{background:#3b7de8}}
</style></head><body>
<div class="logo-wrap">
  {logo_tag}
  <span class="subtitle">Autenticação</span>
</div>
{error_html}
<form method="post" action="/login">
  <div class="field"><label>Usuário</label>
    <input type="text" name="username" autocomplete="username" autofocus /></div>
  <div class="field"><label>Senha</label>
    <input type="password" name="password" autocomplete="current-password" /></div>
  <button type="submit">Entrar</button>
</form>
</body></html>"""


class _SessionAuth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        if request.url.path in ("/login", "/api/ping"):
            return await call_next(request)
        token = request.cookies.get("playline_session")
        if token and token in _SESSIONS:
            return await call_next(request)
        return RedirectResponse(url="/login", status_code=302)


app = FastAPI(title="PlayLine", lifespan=lifespan)
app.add_middleware(_SessionAuth)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
app.include_router(http_router)
app.include_router(ws_router)


@app.websocket("/ws/preview")
async def preview_ws(ws: WebSocket):
    await preview_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()   # mantém vivo; dados fluem apenas servidor→cliente
    except Exception:
        preview_manager.disconnect(ws)


@app.get("/api/ping")
async def ping():
    return {"playline": True}


@app.get("/login")
async def login_page():
    return HTMLResponse(_build_login_html())


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    if form.get("username") == _AUTH_USER and form.get("password") == _AUTH_PASS:
        token = secrets.token_urlsafe(32)
        _SESSIONS.add(token)
        resp = RedirectResponse(url="/", status_code=302)
        resp.set_cookie("playline_session", token, httponly=True, samesite="lax")
        return resp
    return HTMLResponse(_build_login_html(error=True), status_code=401)


@app.post("/api/logout")
async def logout(request: Request):
    """Invalida a sessão atual — o cookie continua no browser mas o token não é mais aceito."""
    token = request.cookies.get("playline_session", "")
    _SESSIONS.discard(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("playline_session")
    return resp


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


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
            window.load_url(f"http://localhost:{port}")
            return


if __name__ == "__main__":
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
        """Garante GPU de alto desempenho para o daemon MPV via registro do Windows.

        Escrito antes de spawnar o daemon — o processo filho já nasce com a preferência correta.
        Em dev, aplica ao Python do venv (sys.executable). Não requer administrador (HKCU).
        """
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
        def close_interface_only(self):
            """Fecha a janela; daemon e servidor continuam rodando."""
            global _closing_confirmed
            _closing_confirmed = True
            if _window:
                _window.destroy()

        def close_all(self):
            """Para o player, encerra o processo do daemon e fecha a janela PyWebView."""
            global _closing_confirmed
            # 1. Para a engine de playlist
            try:
                import asyncio
                import api.routes as _routes
                eng = _routes._playlist_engine
                if eng and eng._loop and eng._loop.is_running():
                    asyncio.run_coroutine_threadsafe(eng.stop(), eng._loop)
            except Exception:
                pass
            # 2. Encerra o processo do daemon via porta 6600
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
            # 3. Invalida a sessão para exigir autenticação no próximo acesso
            _SESSIONS.clear()
            # 4. Fecha a janela
            _closing_confirmed = True
            if _window:
                _window.destroy()

    _pywebview_api = _PyWebViewAPI()
    _window = None  # preenchido abaixo

    def _on_closing():
        """Intercepta o botão X — exibe diálogo customizado (exceto em sessão remota).

        evaluate_js não pode ser chamado de dentro do closing handler (mesmo thread da UI →
        deadlock com WebView2). Lançamos um thread separado e retornamos False imediatamente.
        """
        if _closing_confirmed or _is_remote_session():
            return  # permite fechar normalmente
        def _deferred():
            time.sleep(0.05)
            if _window:
                try:
                    _window.evaluate_js("window._showCloseDialog && window._showCloseDialog()")
                except Exception:
                    pass
        threading.Thread(target=_deferred, daemon=True).start()
        return False  # cancela o fechamento padrão

    def _start_webview(func=None):
        import ctypes
        try:
            if func:
                webview.start(func)
            else:
                webview.start()
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

    if _check_playline_running(18000):
        _PORT = 18000
        _window = webview.create_window(
            "PlayLine",
            f"http://localhost:{_PORT}",
            width=_WIN_W,
            height=_WIN_H,
            x=_cx,
            y=_cy,
            min_size=(960, 600),
            js_api=_pywebview_api,
        )
        _window.events.closing += _on_closing
        _start_webview()
    else:
        _PORT = _find_free_port(18000)
        threading.Thread(target=_run_server, args=(_PORT,), daemon=True).start()
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
        _start_webview(
            lambda: threading.Thread(target=_wait_and_navigate, args=(_window, _PORT), daemon=True).start()
        )
