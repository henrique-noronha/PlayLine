"""Ponto de entrada do PlayLine — inicialização do FastAPI e wiring dos módulos."""

import asyncio
import base64
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

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


class _BasicAuth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
                if user == _AUTH_USER and pw == _AUTH_PASS:
                    return await call_next(request)
            except Exception:
                pass
        return StarletteResponse(
            "Não autorizado",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="PlayLine"'},
        )


app = FastAPI(title="PlayLine", lifespan=lifespan)
app.add_middleware(_BasicAuth)
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


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


def _splash_and_open():
    """Exibe splash screen e abre o browser quando o servidor estiver pronto."""
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
        import urllib.request as _req

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg="#111827")

        W, H = 360, 240
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")

        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).parent.parent

        for name in ("LogoPlayLineD.png", "FavPlayline.png"):
            logo_path = base / "logos" / name
            if logo_path.exists():
                img = Image.open(logo_path).convert("RGBA")
                img.thumbnail((240, 120), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                tk.Label(root, image=photo, bg="#111827").pack(expand=True, pady=(40, 8))
                break

        lbl = tk.Label(root, text="Iniciando servidor…", fg="#6b7280",
                       bg="#111827", font=("Segoe UI", 10))
        lbl.pack(pady=(0, 40))

        def _poll():
            import socket
            for _ in range(60):
                time.sleep(0.5)
                try:
                    s = socket.create_connection(("localhost", 8000), timeout=1)
                    s.close()
                    webbrowser.open("http://localhost:8000")
                    root.after(400, root.destroy)
                    return
                except Exception:
                    pass
            root.after(0, root.destroy)

        threading.Thread(target=_poll, daemon=True).start()
        root.mainloop()

    except Exception as exc:
        logger.warning("Splash screen indisponível: %s", exc)
        time.sleep(4)
        webbrowser.open("http://localhost:8000")


if __name__ == "__main__":
    threading.Thread(target=_splash_and_open, daemon=True).start()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
        log_config=None,
    )
