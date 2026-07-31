"""CRUD de roteiros salvos (saved_schedules)."""

import json
import logging
from datetime import datetime

from db import get_conn

logger = logging.getLogger(__name__)


def list_saved() -> list[dict]:
    """Retorna todos os roteiros salvos sem os itens (id, title, created_at, item_count)."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, created_at, items FROM saved_schedules ORDER BY id DESC"
        ).fetchall()
        result = []
        for r in rows:
            try:
                count = len(json.loads(r["items"]))
            except Exception:
                count = 0
            result.append({
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "item_count": count,
            })
        return result
    finally:
        conn.close()


def save(title: str, items: list[dict]) -> int:
    """Salva um novo roteiro. Retorna o id gerado."""
    conn = get_conn()
    try:
        created_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        items_json = json.dumps(items, ensure_ascii=False)
        with conn:
            cur = conn.execute(
                "INSERT INTO saved_schedules (title, created_at, items) VALUES (?, ?, ?)",
                (title.strip(), created_at, items_json),
            )
        logger.info("[saved_schedules] Roteiro '%s' salvo (%d itens)", title, len(items))
        return cur.lastrowid
    finally:
        conn.close()


def get_items(schedule_id: int) -> list[dict] | None:
    """Retorna os itens de um roteiro salvo, ou None se não existir."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT items FROM saved_schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["items"])
    finally:
        conn.close()


def delete(schedule_id: int) -> bool:
    """Remove um roteiro salvo. Retorna True se encontrado e removido."""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM saved_schedules WHERE id = ?", (schedule_id,)
            )
        return cur.rowcount > 0
    finally:
        conn.close()