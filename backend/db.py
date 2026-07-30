"""Banco de dados SQLite do PlayLine."""

import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH: Path = (
    Path(sys.executable).parent / "playline.db"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "playline.db"
)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schedule (
                position   INTEGER NOT NULL,
                id         TEXT    NOT NULL,
                title      TEXT    NOT NULL DEFAULT '',
                path       TEXT    NOT NULL DEFAULT '',
                live       INTEGER NOT NULL DEFAULT 0,
                start_time REAL,
                end_time   REAL,
                duration   REAL
            );

            CREATE TABLE IF NOT EXISTS checkpoint (
                id       INTEGER PRIMARY KEY CHECK (id = 1),
                path     TEXT    NOT NULL,
                position REAL    NOT NULL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                date            TEXT    NOT NULL,
                title           TEXT    NOT NULL,
                path            TEXT    NOT NULL,
                started_at      TEXT    NOT NULL,
                ended_at        TEXT,
                duration_played REAL    NOT NULL DEFAULT 0,
                end_reason      TEXT,
                had_pause       INTEGER NOT NULL DEFAULT 0
            );
        """)
    logger.info("[db] Banco inicializado: %s", DB_PATH)


def migrate_from_json(data_dir: Path) -> None:
    """Importa dados legados de JSON para SQLite e renomeia os originais como .bak."""
    import json

    conn = get_conn()
    try:
        # ── schedule.json ──────────────────────────────────────────────
        sched = data_dir / "schedule.json"
        if sched.exists():
            try:
                items = json.loads(sched.read_text(encoding="utf-8"))
                with conn:
                    if conn.execute("SELECT COUNT(*) FROM schedule").fetchone()[0] == 0 and items:
                        conn.executemany(
                            "INSERT INTO schedule (position,id,title,path,live,start_time,end_time,duration)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            [(i, it.get("id", ""), it.get("title", ""), it.get("path", ""),
                              1 if it.get("live") else 0,
                              it.get("start_time"), it.get("end_time"), it.get("duration"))
                             for i, it in enumerate(items)],
                        )
                sched.rename(sched.with_suffix(".json.bak"))
                logger.info("[db] schedule.json migrado (%d itens)", len(items))
            except Exception as exc:
                logger.warning("[db] Falha ao migrar schedule: %s", exc)

        # ── checkpoint.json ────────────────────────────────────────────
        cp_file = data_dir / "checkpoint.json"
        if cp_file.exists():
            try:
                cp = json.loads(cp_file.read_text(encoding="utf-8"))
                with conn:
                    if conn.execute("SELECT COUNT(*) FROM checkpoint").fetchone()[0] == 0 and cp:
                        conn.execute(
                            "INSERT OR REPLACE INTO checkpoint (id, path, position) VALUES (1,?,?)",
                            (cp.get("path", ""), cp.get("position", 0.0)),
                        )
                cp_file.rename(cp_file.with_suffix(".json.bak"))
                logger.info("[db] checkpoint.json migrado")
            except Exception as exc:
                logger.warning("[db] Falha ao migrar checkpoint: %s", exc)

        # ── history.json ───────────────────────────────────────────────
        hist = data_dir / "history.json"
        if hist.exists():
            try:
                entries = json.loads(hist.read_text(encoding="utf-8"))
                with conn:
                    if conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0 and entries:
                        conn.executemany(
                            "INSERT INTO history"
                            " (date,title,path,started_at,ended_at,duration_played,end_reason,had_pause)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            [(e.get("date", ""), e.get("title", ""), e.get("path", ""),
                              e.get("started_at", ""), e.get("ended_at"),
                              e.get("duration_played", 0), e.get("end_reason"),
                              1 if e.get("had_pause") else 0)
                             for e in entries],
                        )
                hist.rename(hist.with_suffix(".json.bak"))
                logger.info("[db] history.json migrado (%d entradas)", len(entries))
            except Exception as exc:
                logger.warning("[db] Falha ao migrar history: %s", exc)
    finally:
        conn.close()
