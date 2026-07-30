"""Testes para daemon/checkpoint.py — write, flush, clear via SQLite."""

from pathlib import Path
import pytest
import db
from daemon import checkpoint


@pytest.fixture(autouse=True)
def patch_daemon_db(monkeypatch):
    """Redireciona o _DB_PATH do daemon para o mesmo banco temporário do teste."""
    monkeypatch.setattr(checkpoint, "_DB_PATH", db.DB_PATH)


_DUMMY = Path("ignorado")  # checkpoint_path não é mais usado


def test_write_cria_registro():
    checkpoint.write(_DUMMY, "C:\\clip.mp4")

    conn = db.get_conn()
    row = conn.execute("SELECT * FROM checkpoint WHERE id=1").fetchone()
    conn.close()

    assert row is not None
    assert row["path"] == "C:\\clip.mp4"
    assert row["position"] == pytest.approx(0.0)


def test_write_sobrescreve_registro_anterior():
    checkpoint.write(_DUMMY, "C:\\primeiro.mp4")
    checkpoint.write(_DUMMY, "C:\\segundo.mp4")

    conn = db.get_conn()
    rows = conn.execute("SELECT COUNT(*) FROM checkpoint").fetchone()[0]
    row  = conn.execute("SELECT path FROM checkpoint WHERE id=1").fetchone()
    conn.close()

    assert rows == 1
    assert row["path"] == "C:\\segundo.mp4"


def test_flush_atualiza_posicao():
    checkpoint.write(_DUMMY, "C:\\clip.mp4")
    result = checkpoint.flush(_DUMMY, 123.4)

    conn = db.get_conn()
    row = conn.execute("SELECT position FROM checkpoint WHERE id=1").fetchone()
    conn.close()

    assert result is True
    assert row["position"] == pytest.approx(123.4)


def test_flush_sem_registro_retorna_false():
    result = checkpoint.flush(_DUMMY, 10.0)
    assert result is False


def test_clear_remove_registro():
    checkpoint.write(_DUMMY, "C:\\clip.mp4")
    checkpoint.clear(_DUMMY)

    conn = db.get_conn()
    row = conn.execute("SELECT * FROM checkpoint WHERE id=1").fetchone()
    conn.close()

    assert row is None


def test_clear_sem_registro_nao_levanta():
    checkpoint.clear(_DUMMY)  # não deve lançar exceção
