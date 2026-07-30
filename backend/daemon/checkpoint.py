"""Gerenciamento do checkpoint de posição para retomada após crash."""

import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger("mpv_daemon")

_DB_PATH: Path = (
    Path(sys.executable).parent / "playline.db"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent / "playline.db"
)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH), timeout=5)
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
