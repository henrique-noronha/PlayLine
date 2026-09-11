"""Persistência de chaves fora das colunas fixas de `schedule` (type, clip_overlays...).

Antes, save_schedule() descartava essas chaves e um reinício do servidor
apagava o tipo dos itens de captura e a automação de overlay por clipe.
"""
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import core.db as db
from core.db import get_conn
from core.playlist import PlaylistEngine


def _engine():
    player = MagicMock()
    player.prefetch_yt = MagicMock()
    player.get_playing_path = MagicMock(return_value=None)
    return PlaylistEngine(player=player, broadcast=AsyncMock())


def test_type_e_clip_overlays_sobrevivem_ao_reload():
    items = [
        {"id": "c1", "type": "capture", "live": True, "title": "Webcam",
         "path": "av://dshow:video=Cam", "duration": 0},
        {"id": "v1", "title": "VT", "path": "C:\\v.mp4", "duration": 60,
         "clip_overlays": {"logo1": {"active": True, "corner": "br"}}},
    ]
    _engine().save_schedule(items)

    loaded = _engine().load_schedule()  # engine nova = "servidor reiniciado"
    assert loaded[0]["type"] == "capture"
    assert loaded[0]["live"] is True
    assert loaded[1]["clip_overlays"] == {"logo1": {"active": True, "corner": "br"}}
    assert "extra" not in loaded[0] and "extra" not in loaded[1]


def test_item_sem_chaves_extras_grava_null():
    _engine().save_schedule([{"id": "v1", "title": "VT", "path": "C:\\v.mp4", "duration": 60}])
    conn = get_conn()
    row = conn.execute("SELECT extra FROM schedule").fetchone()
    conn.close()
    assert row["extra"] is None


def test_extra_corrompido_nao_derruba_o_load():
    conn = get_conn()
    conn.execute(
        "INSERT INTO schedule (position,id,title,path,live,extra) VALUES (0,'x','X','C:\\x.mp4',0,'{nao é json')"
    )
    conn.commit()
    conn.close()
    loaded = _engine().load_schedule()
    assert len(loaded) == 1 and loaded[0]["id"] == "x" and "extra" not in loaded[0]


def test_migracao_adiciona_coluna_extra_em_banco_antigo(tmp_path, monkeypatch):
    """Banco criado por uma versão anterior (sem a coluna) precisa migrar sem perder nada."""
    old = tmp_path / "old.db"
    monkeypatch.setattr(db, "DB_PATH", old)
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE schedule (position INTEGER NOT NULL, id TEXT NOT NULL,"
        " title TEXT NOT NULL DEFAULT '', path TEXT NOT NULL DEFAULT '',"
        " live INTEGER NOT NULL DEFAULT 0, start_time REAL, end_time REAL, duration REAL)"
    )
    conn.execute("INSERT INTO schedule (position,id,title,path) VALUES (0,'old','Antigo','C:\\a.mp4')")
    conn.commit()
    conn.close()

    db.init_db()
    db.init_db()  # idempotente: não pode tentar adicionar a coluna duas vezes

    conn = db.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(schedule)")}
    rows = conn.execute("SELECT id, extra FROM schedule").fetchall()
    conn.close()
    assert "extra" in cols
    assert rows[0]["id"] == "old" and rows[0]["extra"] is None


def test_env_playline_db_sobrescreve_caminho(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYLINE_DB", str(tmp_path / "isolado.db"))
    assert db._default_db_path() == tmp_path / "isolado.db"
