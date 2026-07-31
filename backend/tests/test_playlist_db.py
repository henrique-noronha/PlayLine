"""Testes para PlaylistEngine — operações de schedule e checkpoint no SQLite."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from core.db import get_conn
from core.playlist import PlaylistEngine


@pytest.fixture
def engine():
    player = MagicMock()
    player.prefetch_yt = MagicMock()
    player.get_playing_path = MagicMock(return_value=None)
    broadcast = AsyncMock()
    return PlaylistEngine(player=player, broadcast=broadcast)


# ── load_schedule ──────────────────────────────────────────────────────────

def test_load_schedule_vazio(engine):
    assert engine.load_schedule() == []


def test_load_schedule_le_banco(engine):
    conn = get_conn()
    conn.execute(
        "INSERT INTO schedule (position,id,title,path,live) VALUES (0,'i1','VT 1','C:\\v1.mp4',0)"
    )
    conn.execute(
        "INSERT INTO schedule (position,id,title,path,live) VALUES (1,'i2','VT 2','C:\\v2.mp4',0)"
    )
    conn.commit()
    conn.close()

    items = engine.load_schedule()
    assert len(items) == 2
    assert items[0]["id"] == "i1"
    assert items[1]["id"] == "i2"


# ── save_schedule ──────────────────────────────────────────────────────────

def test_save_e_load_roundtrip(engine):
    items = [
        {"id": "a", "title": "Clip A", "path": "C:\\a.mp4", "live": False},
        {"id": "b", "title": "Clip B", "path": "C:\\b.mp4", "live": False},
    ]
    engine.save_schedule(items)

    engine2 = PlaylistEngine(player=engine._player, broadcast=engine._broadcast)
    loaded = engine2.load_schedule()

    assert len(loaded) == 2
    assert loaded[0]["id"] == "a"
    assert loaded[1]["id"] == "b"


def test_save_preserva_flag_live(engine):
    items = [{"id": "yt", "title": "Live", "path": "https://yt.be/x", "live": True}]
    engine.save_schedule(items)

    engine2 = PlaylistEngine(player=engine._player, broadcast=engine._broadcast)
    loaded = engine2.load_schedule()

    assert loaded[0]["live"] is True


def test_save_preserva_start_end_time(engine):
    items = [{"id": "c", "title": "Cortado", "path": "C:\\c.mp4",
              "live": False, "start_time": 5.0, "end_time": 30.0}]
    engine.save_schedule(items)

    engine2 = PlaylistEngine(player=engine._player, broadcast=engine._broadcast)
    loaded = engine2.load_schedule()

    assert loaded[0]["start_time"] == pytest.approx(5.0)
    assert loaded[0]["end_time"] == pytest.approx(30.0)


def test_save_substitui_roteiro_anterior(engine):
    engine.save_schedule([{"id": "x", "title": "X", "path": "/x.mp4", "live": False}])
    engine.save_schedule([{"id": "y", "title": "Y", "path": "/y.mp4", "live": False}])

    engine2 = PlaylistEngine(player=engine._player, broadcast=engine._broadcast)
    loaded = engine2.load_schedule()

    assert len(loaded) == 1
    assert loaded[0]["id"] == "y"


def test_save_roteiro_vazio(engine):
    engine.save_schedule([{"id": "x", "title": "X", "path": "/x.mp4", "live": False}])
    engine.save_schedule([])

    engine2 = PlaylistEngine(player=engine._player, broadcast=engine._broadcast)
    assert engine2.load_schedule() == []


# ── _read_checkpoint ───────────────────────────────────────────────────────

def test_read_checkpoint_sem_dado(engine):
    assert engine._read_checkpoint() is None


def test_read_checkpoint_retorna_corretamente(engine):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO checkpoint (id, path, position) VALUES (1, ?, ?)",
        ("C:\\video.mp4", 42.5),
    )
    conn.commit()
    conn.close()

    cp = engine._read_checkpoint()
    assert cp is not None
    assert cp["path"] == "C:\\video.mp4"
    assert cp["position"] == pytest.approx(42.5)
