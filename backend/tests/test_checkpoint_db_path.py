"""O checkpoint do daemon tem que cair no MESMO banco que o servidor lê.

Regressão: daemon/checkpoint.py derivava o caminho de __file__ e, em dev,
gravava em backend/playline.db (arquivo sem tabelas) enquanto core/db.py lia
backend/core/playline.db, então a recuperação de crash nunca funcionava fora
do build congelado, e falhava em silêncio.
"""
import core.db as db
from daemon import checkpoint


def test_checkpoint_usa_o_db_path_do_servidor(use_temp_db):
    assert checkpoint._db_path() == use_temp_db


def test_ciclo_write_flush_clear_visivel_pelo_servidor():
    checkpoint.write(None, "C:\\v.mp4")
    assert checkpoint.flush(None, 42.5) is True

    conn = db.get_conn()
    row = conn.execute("SELECT path, position FROM checkpoint WHERE id=1").fetchone()
    conn.close()
    assert row["path"] == "C:\\v.mp4"
    assert row["position"] == 42.5

    checkpoint.clear(None)
    conn = db.get_conn()
    assert conn.execute("SELECT COUNT(*) FROM checkpoint").fetchone()[0] == 0
    conn.close()


def test_flush_sem_checkpoint_retorna_false():
    assert checkpoint.flush(None, 1.0) is False
