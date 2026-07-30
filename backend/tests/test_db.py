"""Testes para db.py — inicialização e migração de JSON."""

import json
import db
from db import get_conn, migrate_from_json


def test_tabelas_criadas():
    conn = get_conn()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert {"schedule", "checkpoint", "history"} <= tables


def test_wal_mode_ativo():
    conn = get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_migrate_schedule(tmp_path):
    dados = [
        {"id": "i1", "title": "VT Abertura", "path": "C:\\a.mp4", "live": False},
        {"id": "i2", "title": "VT Encerramento", "path": "C:\\b.mp4", "live": False},
    ]
    (tmp_path / "schedule.json").write_text(json.dumps(dados), encoding="utf-8")

    migrate_from_json(tmp_path)

    conn = get_conn()
    rows = conn.execute("SELECT * FROM schedule ORDER BY position").fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0]["title"] == "VT Abertura"
    assert rows[1]["title"] == "VT Encerramento"
    # arquivo original renomeado para .bak
    assert not (tmp_path / "schedule.json").exists()
    assert (tmp_path / "schedule.json.bak").exists()


def test_migrate_nao_sobrescreve_dados_existentes(tmp_path):
    """Se o banco já tem dados, a migração não deve duplicar."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO schedule (position,id,title,path,live) VALUES (0,'x','Existente','/x.mp4',0)"
    )
    conn.commit()
    conn.close()

    dados = [{"id": "novo", "title": "Novo", "path": "/n.mp4", "live": False}]
    (tmp_path / "schedule.json").write_text(json.dumps(dados), encoding="utf-8")

    migrate_from_json(tmp_path)

    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
    conn.close()
    assert count == 1  # permanece o dado existente, não importou o JSON


def test_migrate_checkpoint(tmp_path):
    cp = {"path": "C:\\video.mp4", "position": 87.3}
    (tmp_path / "checkpoint.json").write_text(json.dumps(cp), encoding="utf-8")

    migrate_from_json(tmp_path)

    conn = get_conn()
    row = conn.execute("SELECT * FROM checkpoint WHERE id=1").fetchone()
    conn.close()

    assert row["path"] == "C:\\video.mp4"
    assert abs(row["position"] - 87.3) < 0.01
    assert not (tmp_path / "checkpoint.json").exists()


def test_migrate_history(tmp_path):
    entradas = [
        {"date": "2026-07-30", "title": "Clip X", "path": "/x.mp4",
         "started_at": "10:00:00", "ended_at": "10:05:00",
         "duration_played": 300, "end_reason": "completed", "had_pause": False},
        {"date": "2026-07-30", "title": "Clip Y", "path": "/y.mp4",
         "started_at": "10:05:00", "ended_at": "10:08:00",
         "duration_played": 180, "end_reason": "skipped", "had_pause": True},
    ]
    (tmp_path / "history.json").write_text(json.dumps(entradas), encoding="utf-8")

    migrate_from_json(tmp_path)

    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    conn.close()

    assert count == 2
    assert not (tmp_path / "history.json").exists()
