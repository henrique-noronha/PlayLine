"""Ponto de entrada do PlayLine — inicialização do FastAPI e wiring dos módulos."""

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.player import Player
from core.playlist import PlaylistEngine
from api.routes import router as http_router, setup as setup_routes
from api.websocket import router as ws_router, setup as setup_ws

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
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

app = FastAPI(title="PlayLine", lifespan=lifespan)
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


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
