"""Registro de histórico de exibição do PlayLine."""

import logging
import threading
from datetime import datetime

from .db import get_conn

logger = logging.getLogger(__name__)

_REASON_LABEL = {
    "completed":   "Concluído",
    "stopped":     "Parado",
    "skipped":     "Avançado",
    "interrupted": "Interrompido",
    "error":       "Erro",
}


class HistoryManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._current: dict | None = None

    def open_entry(self, title: str, path: str) -> None:
        self.close_entry("interrupted")
        now = datetime.now()
        with self._lock:
            self._current = {
                "date":        now.strftime("%Y-%m-%d"),
                "title":       title,
                "path":        path,
                "started_at":  now.strftime("%H:%M:%S"),
                "_started_ts": now.timestamp(),
                "had_pause":   False,
            }

    def close_entry(self, reason: str) -> None:
        with self._lock:
            if self._current is None:
                return
            entry = self._current
            self._current = None

        now = datetime.now()
        duration = max(0, round(now.timestamp() - entry.pop("_started_ts")))
        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO history"
                    " (date,title,path,started_at,ended_at,duration_played,end_reason,had_pause)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (entry["date"], entry["title"], entry["path"], entry["started_at"],
                     now.strftime("%H:%M:%S"), duration, reason,
                     1 if entry["had_pause"] else 0),
                )
        except Exception as exc:
            logger.error("[history] Erro ao salvar: %s", exc)

    def mark_pause(self) -> None:
        with self._lock:
            if self._current:
                self._current["had_pause"] = True

    def get_history(self, date: str | None = None, limit: int = 200) -> list[dict]:
        try:
            conn = get_conn()
            if date:
                rows = conn.execute(
                    "SELECT * FROM history WHERE date=? ORDER BY id DESC LIMIT ?",
                    (date, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            conn.close()
            result = []
            for r in rows:
                e = dict(r)
                e["had_pause"] = bool(e["had_pause"])
                e["end_reason_label"] = _REASON_LABEL.get(
                    e.get("end_reason", ""), e.get("end_reason", "—")
                )
                result.append(e)
            return result
        except Exception as exc:
            logger.error("[history] Erro ao consultar: %s", exc)
            return []

    def get_stats(self) -> dict:
        """Retorna estatísticas agregadas: top clipes, totais e atividade por data."""
        try:
            conn = get_conn()

            top = conn.execute("""
                SELECT path, title,
                       COUNT(*)                        AS play_count,
                       SUM(duration_played)            AS total_seconds,
                       ROUND(SUM(duration_played)/3600.0, 2) AS total_hours
                FROM   history
                GROUP  BY path
                ORDER  BY play_count DESC
            """).fetchall()

            totals = conn.execute("""
                SELECT COUNT(*)                             AS total_plays,
                       ROUND(SUM(duration_played)/3600.0,2) AS total_hours,
                       COUNT(DISTINCT date)                 AS total_days
                FROM   history
            """).fetchone()

            by_date = conn.execute("""
                SELECT date,
                       COUNT(*)            AS plays,
                       SUM(duration_played) AS seconds
                FROM   history
                GROUP  BY date
                ORDER  BY date DESC
                LIMIT  30
            """).fetchall()

            conn.close()
            return {
                "top_clips":   [dict(r) for r in top],
                "total_plays": totals["total_plays"] or 0,
                "total_hours": totals["total_hours"] or 0.0,
                "total_days":  totals["total_days"] or 0,
                "by_date":     [dict(r) for r in by_date],
            }
        except Exception as exc:
            logger.error("[history] Erro ao obter stats: %s", exc)
            return {"top_clips": [], "total_plays": 0, "total_hours": 0.0, "total_days": 0, "by_date": []}
