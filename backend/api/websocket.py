"""WebSocket endpoint e handler de comandos."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

_playlist_engine = None
_manager = None
_session_ok = None  # callable(token) -> bool; None desliga a checagem (testes)

# Código de fechamento na faixa livre para aplicações (4000-4999). Na prática,
# como o close() acontece ANTES do accept(), o Starlette nem faz o upgrade:
# responde ao handshake com HTTP 403 (verificado ao vivo), e o navegador só vê
# um close 1006. Por isso frontend/core/ws.js checa um endpoint protegido ao
# perder a conexão e redireciona para /login se a sessão expirou.
WS_CLOSE_UNAUTHORIZED = 4401


def setup(playlist_engine, manager, session_ok=None):
    global _playlist_engine, _manager, _session_ok
    _playlist_engine = playlist_engine
    _manager = manager
    _session_ok = session_ok


def ws_token(ws: WebSocket) -> str:
    """Token de sessão do handshake: cookie normal ou ?session_token= (auto-login do PyWebView)."""
    return ws.cookies.get("playline_session") or ws.query_params.get("session_token") or ""


async def ws_authorized(ws: WebSocket) -> bool:
    """Fecha o socket com 4401 e retorna False se a sessão não for válida.

    O middleware HTTP de sessão deixa passar todo upgrade de WebSocket (não dá
    para redirecionar um handshake para /login), então a checagem tem que ser
    feita aqui, no endpoint. Sem isso, qualquer host que alcance a porta
    controla o playout sem senha.
    """
    if _session_ok is None or _session_ok(ws_token(ws)):
        return True
    await ws.close(code=WS_CLOSE_UNAUTHORIZED)
    return False


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    if not await ws_authorized(ws):
        return
    await _manager.connect(ws)
    try:
        await ws.send_text(json.dumps(_playlist_engine.state()))
    except Exception as exc:
        logger.error("Erro ao enviar estado inicial: %s", exc)
    _playlist_engine.request_logo_list()
    _playlist_engine.request_logo_state()
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
    elif action == "set_transition":
        # Botão do cabeçalho do roteiro: {"type": "cut"|"fade"} (duração opcional)
        try:
            await _playlist_engine.set_transition({k: cmd[k] for k in ("type", "duration") if k in cmd})
        except ValueError as exc:
            logger.warning("set_transition inválido: %s", exc)
    elif action == "set_logo":
        _playlist_engine.set_logo(
            cmd.get("slot", 1), cmd.get("filename", ""),
            cmd.get("corner", "br"), cmd.get("active", False),
        )
    elif action == "set_text_overlay":
        _playlist_engine.set_text_overlay({
            "active":      bool(cmd.get("active",      False)),
            "show_time":   bool(cmd.get("show_time",   True)),
            "show_temp":   bool(cmd.get("show_temp",   True)),
            "corner":      str(cmd.get("corner",      "tl")),
            "city":        str(cmd.get("city",        "Palmas")),
            "manual_temp": str(cmd.get("manual_temp", "")),
        })
    else:
        logger.warning("Ação desconhecida: %s", action)
