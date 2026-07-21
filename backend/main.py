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
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from core.player import Player
from core.playlist import PlaylistEngine
from api.routes import router as http_router, setup as setup_routes
from api.websocket import router as ws_router, setup as setup_ws

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
else:
    FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


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

    player_instance = Player(
        on_end_file=_on_end,
        on_position=_on_position,
        on_logo_list=_on_logo_list,
        on_text_overlay_state=_on_text_overlay_state,
        on_preview_frame=_on_preview_frame,
    )
    playlist_engine = PlaylistEngine(player=player_instance, broadcast=manager.broadcast)
    playlist_engine.set_event_loop(loop)
    playlist_engine.load_schedule()

    setup_routes(playlist_engine, manager)
    setup_ws(playlist_engine, manager)

    # Detecta se o daemon já estava reproduzindo algo (crash/reinício do servidor)
    await loop.run_in_executor(None, playlist_engine.restore_after_crash)

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
        if request.url.path == "/login":
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


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


def _run_server():
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
        log_config=None,
    )


def _wait_and_navigate(window):
    import socket
    for _ in range(60):
        time.sleep(0.5)
        try:
            s = socket.create_connection(("localhost", 8000), timeout=1)
            s.close()
            window.load_url("http://localhost:8000")
            return
        except Exception:
            pass


if __name__ == "__main__":
    import webview

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

    _splash = f"""<!DOCTYPE html><html><body style="margin:0;background:#111827;
        display:flex;flex-direction:column;align-items:center;justify-content:center;
        height:100vh;gap:24px">
        {_logo_html}
        <p style="color:#6b7280;font-family:'Segoe UI',sans-serif;font-size:13px;margin:0">
            Iniciando servidor…
        </p></body></html>"""

    def _server_running() -> bool:
        import socket
        try:
            s = socket.create_connection(("localhost", 8000), timeout=1)
            s.close()
            return True
        except Exception:
            return False

    if _server_running():
        _window = webview.create_window(
            "PlayLine",
            "http://localhost:8000",
            width=1440,
            height=860,
            min_size=(960, 600),
        )
        webview.start()
    else:
        threading.Thread(target=_run_server, daemon=True).start()
        _window = webview.create_window(
            "PlayLine",
            html=_splash,
            width=1440,
            height=860,
            min_size=(960, 600),
        )
        webview.start(
            lambda: threading.Thread(target=_wait_and_navigate, args=(_window,), daemon=True).start()
        )
