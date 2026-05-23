"""
Ponto de entrada do sistema de playout.
FastAPI + WebSocket + servindo o frontend estático.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from player import Player
from playlist import PlaylistEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# ------------------------------------------------------------------ #
# Gerenciador de conexões WebSocket                                   #
# ------------------------------------------------------------------ #

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


manager = ConnectionManager()
playlist_engine: PlaylistEngine | None = None
player_instance: Player | None = None


# ------------------------------------------------------------------ #
# Lifecycle                                                            #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    global playlist_engine, player_instance
    loop = asyncio.get_event_loop()

    def _on_end(reason: str):
        if playlist_engine:
            playlist_engine.on_end_file(reason)

    player_instance = Player(on_end_file=_on_end)
    playlist_engine = PlaylistEngine(player=player_instance, broadcast=manager.broadcast)
    playlist_engine.set_event_loop(loop)
    playlist_engine.load_schedule()

    logger.info("Sistema de playout iniciado")
    yield

    if player_instance:
        player_instance.shutdown()
    logger.info("Sistema encerrado")


app = FastAPI(title="Playout TV", lifespan=lifespan)

# Servir frontend
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ------------------------------------------------------------------ #
# Rotas HTTP                                                           #
# ------------------------------------------------------------------ #

@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/schedule")
async def get_schedule():
    return playlist_engine.get_schedule()


@app.put("/api/schedule")
async def update_schedule(items: list[dict]):
    playlist_engine.save_schedule(items)
    await manager.broadcast({"event": "schedule_updated", "items": items})
    return {"ok": True}


@app.get("/api/state")
async def get_state():
    return playlist_engine.state()


# ------------------------------------------------------------------ #
# WebSocket                                                            #
# ------------------------------------------------------------------ #

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_text(json.dumps(playlist_engine.state()))
    except Exception as exc:
        logger.error("Erro ao enviar estado inicial: %s", exc)
    try:
        while True:
            raw = await ws.receive_text()
            await handle_command(json.loads(raw))
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as exc:
        logger.error("Erro no WS: %s", exc)
        manager.disconnect(ws)


async def handle_command(cmd: dict):
    action = cmd.get("action")
    logger.info("Comando recebido: %s", action)

    if action == "play":
        await playlist_engine.play()
    elif action == "pause":
        await playlist_engine.pause_toggle()
    elif action == "stop":
        await playlist_engine.stop()
    elif action == "next":
        await playlist_engine.next_item()
    elif action == "prev":
        await playlist_engine.prev_item()
    elif action == "jump":
        index = cmd.get("index", 0)
        await playlist_engine.jump_to(index)
    elif action == "state":
        await manager.broadcast(playlist_engine.state())
    elif action == "reload_schedule":
        items = playlist_engine.load_schedule()
        await manager.broadcast({"event": "schedule_updated", "items": items})
    else:
        logger.warning("Ação desconhecida: %s", action)


# ------------------------------------------------------------------ #
# Entrypoint                                                           #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
