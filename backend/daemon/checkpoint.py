"""Gerenciamento do checkpoint de posição para retomada após crash."""

import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger("mpv_daemon")


def _db_path() -> Path:
    """Mesmo arquivo que o servidor usa (core.db.DB_PATH), lido na hora da chamada.

    Não recalcula o caminho aqui: em dev, derivar de __file__ apontava para
    backend/playline.db enquanto o servidor lia backend/core/playline.db, e o
    checkpoint de crash ia para um arquivo sem tabelas (falha silenciosa).
    """
    try:
        from core import db as _db
    except ImportError:
        from ..core import db as _db
    return _db.DB_PATH


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_db_path()), timeout=5)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def write(checkpoint_path: Path, playing_path: str) -> None:
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO checkpoint (id, path, position) VALUES (1, ?, 0.0)",
                (playing_path,),
            )
    except Exception:
        pass


def flush(checkpoint_path: Path, position: float) -> bool:
    try:
        with _conn() as conn:
            cur = conn.execute("UPDATE checkpoint SET position=? WHERE id=1", (position,))
        return cur.rowcount > 0
    except Exception:
        return False


def clear(checkpoint_path: Path) -> None:
    try:
        with _conn() as conn:
            conn.execute("DELETE FROM checkpoint WHERE id=1")
    except Exception:
        pass
