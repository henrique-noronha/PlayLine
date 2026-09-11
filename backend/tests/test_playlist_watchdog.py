"""Salvaguardas de operação 24/7 do PlaylistEngine:
watchdog de clipe local travado, limite de reabertura do MPV e auto-resume
a partir do checkpoint na inicialização.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import core.playlist as pl
from core.db import get_conn


def _engine(items):
    player = MagicMock()
    player.prefetch_yt = MagicMock()
    player.get_playing_path = MagicMock(return_value=None)
    player._connected = True
    eng = pl.PlaylistEngine(player=player, broadcast=AsyncMock())
    eng._items = items
    return eng


_LOCAL = [{"id": "v", "path": "C:\\v.mp4", "title": "VT", "duration": 60}]
_LIVE  = [{"id": "l", "path": "https://www.youtube.com/watch?v=x", "title": "Live", "live": True}]


# ── watchdog de clipe local ──────────────────────────────────────────────

def test_clipe_local_com_posicao_parada_e_travamento():
    eng = _engine(_LOCAL)
    eng._running, eng._index = True, 0
    eng._pos_ts = time.monotonic() - pl._LOCAL_STALL_SEC - 1
    assert eng._local_stalled(time.monotonic()) is True


def test_posicao_avancando_nao_e_travamento():
    eng = _engine(_LOCAL)
    eng._running, eng._index = True, 0
    eng._pos_ts = time.monotonic() - pl._LOCAL_STALL_SEC - 1
    eng.on_position(10.0)  # posição nova zera o relógio
    assert eng._local_stalled(time.monotonic()) is False


def test_on_position_ignora_variacao_abaixo_do_limiar():
    eng = _engine(_LOCAL)
    eng._running, eng._index = True, 0
    eng.on_position(5.0)
    ts = eng._pos_ts
    eng.on_position(5.01)
    assert eng._pos_ts == ts


def test_pausado_nao_conta_como_travamento():
    eng = _engine(_LOCAL)
    eng._running, eng._paused, eng._index = True, True, 0
    eng._pos_ts = time.monotonic() - 999
    assert eng._local_stalled(time.monotonic()) is False


def test_parado_nao_conta_como_travamento():
    eng = _engine(_LOCAL)
    eng._running, eng._index = False, 0
    eng._pos_ts = time.monotonic() - 999
    assert eng._local_stalled(time.monotonic()) is False


def test_live_tem_o_proprio_watchdog_e_e_ignorada_aqui():
    eng = _engine(_LIVE)
    eng._running, eng._index = True, 0
    eng._pos_ts = time.monotonic() - 999
    assert eng._local_stalled(time.monotonic()) is False


def test_retomar_da_pausa_zera_o_relogio(monkeypatch):
    import asyncio
    eng = _engine(_LOCAL)
    eng._running, eng._index, eng._paused = True, 0, True
    eng._pos_ts = time.monotonic() - 999
    asyncio.run(eng.pause_toggle())  # despausa
    assert eng._paused is False
    assert eng._local_stalled(time.monotonic()) is False


# ── limite de reabertura após mpv_closed ─────────────────────────────────

def test_reabertura_do_mpv_e_limitada_por_janela():
    eng = _engine([])
    for _ in range(pl._MPV_REOPEN_MAX):
        assert eng._allow_mpv_reopen() is True
    assert eng._allow_mpv_reopen() is False


def test_reabertura_volta_a_ser_permitida_quando_a_janela_expira():
    eng = _engine([])
    eng._mpv_reopen_ts = [time.monotonic() - pl._MPV_REOPEN_WINDOW - 1] * pl._MPV_REOPEN_MAX
    assert eng._allow_mpv_reopen() is True


# ── auto-resume a partir do checkpoint ───────────────────────────────────

def _capture_resume(monkeypatch):
    calls = []

    def fake_run(coro, loop):
        calls.append(coro)
        coro.close()  # evita "coroutine was never awaited"

    monkeypatch.setattr(pl.asyncio, "run_coroutine_threadsafe", fake_run)
    return calls


def _write_checkpoint(path, pos):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO checkpoint (id,path,position) VALUES (1,?,?)", (path, pos))
    conn.commit()
    conn.close()


def test_checkpoint_de_item_do_roteiro_retoma_sozinho(monkeypatch):
    calls = _capture_resume(monkeypatch)
    eng = _engine(_LOCAL)
    eng._loop = object()
    _write_checkpoint("C:\\v.mp4", 12.0)
    eng.restore_after_crash()
    assert len(calls) == 1


def test_sem_checkpoint_fica_ocioso(monkeypatch):
    calls = _capture_resume(monkeypatch)
    eng = _engine(_LOCAL)
    eng._loop = object()
    eng.restore_after_crash()
    assert calls == []


def test_checkpoint_de_item_que_nao_esta_no_roteiro_e_ignorado(monkeypatch):
    calls = _capture_resume(monkeypatch)
    eng = _engine(_LOCAL)
    eng._loop = object()
    _write_checkpoint("C:\\outro.mp4", 5.0)
    eng.restore_after_crash()
    assert calls == []


def test_autoresume_pode_ser_desligado_por_ambiente(monkeypatch):
    monkeypatch.setenv("PLAYLINE_AUTORESUME", "0")
    calls = _capture_resume(monkeypatch)
    eng = _engine(_LOCAL)
    eng._loop = object()
    _write_checkpoint("C:\\v.mp4", 12.0)
    eng.restore_after_crash()
    assert calls == []
