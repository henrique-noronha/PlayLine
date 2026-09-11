"""Autenticação dos WebSockets (/ws e /ws/preview).

O middleware HTTP deixa passar qualquer upgrade de WebSocket, então a checagem
de sessão é feita no endpoint via ws_authorized(). Sem ela, qualquer host que
alcance a porta controla o playout sem login.
"""
import asyncio

import api.websocket as wsmod


class _FakeWS:
    def __init__(self, cookies=None, query=None):
        self.cookies = cookies or {}
        self.query_params = query or {}
        self.closed_with = None

    async def close(self, code=1000):
        self.closed_with = code


def _authorized(ws):
    return asyncio.run(wsmod.ws_authorized(ws))


def test_sem_validador_configurado_libera(monkeypatch):
    monkeypatch.setattr(wsmod, "_session_ok", None)
    ws = _FakeWS()
    assert _authorized(ws) is True
    assert ws.closed_with is None


def test_cookie_de_sessao_valido_libera(monkeypatch):
    monkeypatch.setattr(wsmod, "_session_ok", lambda t: t == "tok")
    assert _authorized(_FakeWS(cookies={"playline_session": "tok"})) is True


def test_session_token_na_query_libera(monkeypatch):
    """Auto-login do PyWebView abre a página com ?session_token= antes do cookie existir."""
    monkeypatch.setattr(wsmod, "_session_ok", lambda t: t == "tok")
    assert _authorized(_FakeWS(query={"session_token": "tok"})) is True


def test_sem_sessao_fecha_com_4401(monkeypatch):
    monkeypatch.setattr(wsmod, "_session_ok", lambda t: False)
    ws = _FakeWS(cookies={"playline_session": "expirado"})
    assert _authorized(ws) is False
    assert ws.closed_with == wsmod.WS_CLOSE_UNAUTHORIZED


def test_setup_registra_o_validador(monkeypatch):
    monkeypatch.setattr(wsmod, "_session_ok", None)
    wsmod.setup(object(), object(), lambda t: t == "x")
    assert wsmod._session_ok("x") is True
    assert wsmod._session_ok("y") is False
