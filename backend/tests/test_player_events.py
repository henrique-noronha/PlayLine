"""Testes para core/player.py — garante que todo evento recebido do daemon
dispara o callback correto.

Regressão: os eventos "audio_level" e "logo_state" já foram adicionados no
daemon sem que o roteamento correspondente fosse lembrado aqui — o Player
simplesmente descartava a mensagem em silêncio. Este arquivo existe pra pegar
esse tipo de esquecimento assim que um novo evento for adicionado.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest

from core.player import Player


@pytest.fixture
def player():
    # Player.__init__ tenta conectar (e até lançar) o daemon de verdade — não
    # queremos isso num teste unitário, então isolamos só o _handle_event.
    with patch.object(Player, "_connect_or_start", lambda self: None):
        p = Player(
            on_end_file=MagicMock(),
            on_position=MagicMock(),
            on_logo_list=MagicMock(),
            on_logo_state=MagicMock(),
            on_text_overlay_state=MagicMock(),
            on_preview_frame=MagicMock(),
            on_file_loaded=MagicMock(),
            on_audio_level=MagicMock(),
        )
    return p


def _todos_callbacks(player):
    return (
        player._on_end_file,
        player._on_position,
        player._on_logo_list,
        player._on_logo_state,
        player._on_text_overlay_state,
        player._on_preview_frame,
        player._on_file_loaded,
        player._on_audio_level,
    )


def test_end_file_dispara_on_end_file(player):
    player._handle_event({"event": "end-file", "reason": "eof"})
    player._on_end_file.assert_called_once_with("eof")


def test_mpv_closed_dispara_on_end_file(player):
    player._handle_event({"event": "mpv_closed"})
    player._on_end_file.assert_called_once_with("mpv_closed")


def test_position_dispara_on_position(player):
    player._handle_event({"event": "position", "pos": 42.5})
    player._on_position.assert_called_once_with(42.5)


def test_logo_list_dispara_on_logo_list(player):
    player._handle_event({"event": "logo_list", "files": ["a.png"]})
    player._on_logo_list.assert_called_once_with(["a.png"])


def test_logo_state_dispara_on_logo_state(player):
    msg = {"event": "logo_state", "state": {"1": {"active": True}}}
    player._handle_event(msg)
    player._on_logo_state.assert_called_once_with(msg)


def test_audio_level_dispara_on_audio_level(player):
    player._handle_event({"event": "audio_level", "db": -12.3})
    player._on_audio_level.assert_called_once_with(-12.3)


def test_text_overlay_state_dispara_on_text_overlay_state(player):
    msg = {"event": "text_overlay_state", "active": True}
    player._handle_event(msg)
    player._on_text_overlay_state.assert_called_once_with(msg)


def test_preview_frame_dispara_on_preview_frame(player):
    player._handle_event({"event": "preview_frame", "data": "base64=="})
    player._on_preview_frame.assert_called_once_with("base64==")


def test_file_loaded_dispara_on_file_loaded(player):
    player._handle_event({"event": "file-loaded"})
    player._on_file_loaded.assert_called_once()


def test_state_response_atualiza_pending_state(player):
    player._pending_state_event = threading.Event()
    player._handle_event({"event": "state_response", "playing_path": "/x.mp4"})
    assert player._pending_state_path == "/x.mp4"
    assert player._pending_state_event.is_set()


def test_evento_desconhecido_nao_dispara_nenhum_callback(player):
    player._handle_event({"event": "algo_que_nao_existe"})
    for callback in _todos_callbacks(player):
        callback.assert_not_called()
