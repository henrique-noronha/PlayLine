"""Registro de histórico de exibição do PlayLine."""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

_HISTORY_PATH: Path = (
    Path(sys.executable).parent / "history.json"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.parent / "history.json"
)

_MAX_ENTRIES = 50_000

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
                "date":            now.strftime("%Y-%m-%d"),
                "title":           title,
                "path":            path,
                "started_at":      now.strftime("%H:%M:%S"),
                "_started_ts":     now.timestamp(),
                "ended_at":        None,
                "duration_played": 0,
                "end_reason":      None,
                "had_pause":       False,
            }

    def close_entry(self, reason: str) -> None:
        with self._lock:
            if self._current is None:
                return
            entry = self._current
            self._current = None

        now = datetime.now()
        entry["ended_at"]        = now.strftime("%H:%M:%S")
        entry["duration_played"] = max(0, round(now.timestamp() - entry.pop("_started_ts")))
        entry["end_reason"]      = reason
        self._append(entry)

    def mark_pause(self) -> None:
        with self._lock:
            if self._current:
                self._current["had_pause"] = True

    def _append(self, entry: dict) -> None:
        try:
            try:
                entries = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                entries = []
            entries.append(entry)
            if len(entries) > _MAX_ENTRIES:
                entries = entries[-_MAX_ENTRIES:]
            _HISTORY_PATH.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.error("[history] Erro ao salvar: %s", exc)

    def get_history(self, date: str | None = None, limit: int = 200) -> list[dict]:
        try:
            entries = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        if date:
            entries = [e for e in entries if e.get("date") == date]
        entries = list(reversed(entries[-limit:]))
        for e in entries:
            e["end_reason_label"] = _REASON_LABEL.get(
                e.get("end_reason", ""), e.get("end_reason", "—")
            )
        return entries
