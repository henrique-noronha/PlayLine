"""WebSocket endpoint e handler de comandos."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

_playlist_engine = None
_manager = None


def setup(playlist_engine, manager):
    global _playlist_engine, _manager
    _playlist_engine = playlist_engine
    _manager = manager


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await _manager.connect(ws)
    try:
        await ws.send_text(json.dumps(_playlist_engine.state()))
    except Exception as exc:
        logger.error("Erro ao enviar estado inicial: %s", exc)
    _playlist_engine.request_logo_list()
    _playlist_engine.request_text_overlay_state()
    try:
        while True:
            raw = await ws.receive_text()
            await _handle_command(json.loads(raw))
    except WebSocketDisconnect:
        _manager.disconnect(ws)
    except Exception as exc:
        logger.error("Erro no WS: %s", exc)
        _manager.disconnect(ws)


async def _handle_command(cmd: dict):
    action = cmd.get("action")
    logger.info("Comando recebido: %s", action)

    if action == "play":
        await _playlist_engine.play()
    elif action == "pause":
        await _playlist_engine.pause_toggle()
    elif action == "stop":
        await _playlist_engine.stop()
    elif action == "next":
        await _playlist_engine.next_item()
    elif action == "prev":
        await _playlist_engine.prev_item()
    elif action == "jump":
        index = cmd.get("index", 0)
        await _playlist_engine.jump_to(index)
    elif action == "state":
        await _manager.broadcast(_playlist_engine.state())
    elif action == "reload_schedule":
        items = _playlist_engine.load_schedule()
        await _manager.broadcast({"event": "schedule_updated", "items": items})
    elif action == "set_volume":
        _playlist_engine.set_volume(cmd.get("volume", 100))
    elif action == "set_logo":
        _playlist_engine.set_logo(
            cmd.get("slot", 1), cmd.get("filename", ""),
            cmd.get("corner", "br"), cmd.get("active", False),
        )
    elif action == "set_text_overlay":
        _playlist_engine.set_text_overlay({
            "active":    bool(cmd.get("active",    False)),
            "show_time": bool(cmd.get("show_time", True)),
            "show_temp": bool(cmd.get("show_temp", True)),
            "corner":    str(cmd.get("corner",    "tl")),
            "city":      str(cmd.get("city",      "Palmas")),
        })
    else:
        logger.warning("Ação desconhecida: %s", action)
