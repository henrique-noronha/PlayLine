import json
from datetime import datetime
from .db import get_conn


def list_saved() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, created_at, items FROM saved_schedules ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            items = json.loads(r["items"]) if r["items"] else []
            result.append({
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "item_count": len(items),
            })
        return result
    finally:
        conn.close()


def save(title: str, items: list) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO saved_schedules (title, created_at, items) VALUES (?, ?, ?)",
            (title, datetime.now().isoformat(timespec="seconds"), json.dumps(items)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_items(schedule_id: int) -> list[dict] | None:
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
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM saved_schedules WHERE id = ?", (schedule_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
