"""Testes para HistoryManager — registro e estatísticas."""

import pytest
from db import get_conn
from core.history import HistoryManager


@pytest.fixture
def hm():
    return HistoryManager()


def _insert(date, title, path, duration, reason, had_pause=False):
    conn = get_conn()
    conn.execute(
        "INSERT INTO history (date,title,path,started_at,ended_at,duration_played,end_reason,had_pause)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (date, title, path, "10:00:00", "10:01:00", duration, reason, 1 if had_pause else 0),
    )
    conn.commit()
    conn.close()


# ── open / close ───────────────────────────────────────────────────────────

def test_close_sem_open_nao_levanta(hm):
    hm.close_entry("stopped")  # não deve lançar exceção


def test_open_close_salva_registro(hm):
    hm.open_entry("Notícia", "/news.mp4")
    hm.close_entry("completed")

    entries = hm.get_history()
    assert len(entries) == 1
    e = entries[0]
    assert e["title"] == "Notícia"
    assert e["path"] == "/news.mp4"
    assert e["end_reason"] == "completed"
    assert e["end_reason_label"] == "Concluído"
    assert e["duration_played"] >= 0
    assert e["had_pause"] is False


def test_mark_pause_registrado(hm):
    hm.open_entry("Esporte", "/sport.mp4")
    hm.mark_pause()
    hm.close_entry("completed")

    assert hm.get_history()[0]["had_pause"] is True


def test_open_duplo_fecha_anterior_como_interrupted(hm):
    hm.open_entry("Clip A", "/a.mp4")
    hm.open_entry("Clip B", "/b.mp4")  # deve fechar A com "interrupted"
    hm.close_entry("completed")

    entries = hm.get_history()
    assert len(entries) == 2
    reasons = {e["title"]: e["end_reason"] for e in entries}
    assert reasons["Clip A"] == "interrupted"
    assert reasons["Clip B"] == "completed"


# ── get_history ────────────────────────────────────────────────────────────

def test_filtro_por_data(hm):
    _insert("2026-07-01", "Antigo", "/old.mp4", 60, "completed")
    _insert("2026-07-30", "Atual",  "/new.mp4", 60, "completed")

    result = hm.get_history(date="2026-07-01")
    assert len(result) == 1
    assert result[0]["title"] == "Antigo"


def test_sem_filtro_retorna_todos(hm):
    _insert("2026-07-01", "A", "/a.mp4", 60, "completed")
    _insert("2026-07-30", "B", "/b.mp4", 60, "skipped")

    assert len(hm.get_history()) == 2


def test_limit_respeitado(hm):
    for i in range(10):
        _insert("2026-07-30", f"Clip {i}", f"/{i}.mp4", 30, "completed")

    assert len(hm.get_history(limit=5)) == 5


def test_ordem_decrescente(hm):
    _insert("2026-07-30", "Primeiro", "/1.mp4", 60, "completed")
    _insert("2026-07-30", "Segundo",  "/2.mp4", 60, "completed")

    entries = hm.get_history()
    assert entries[0]["title"] == "Segundo"  # mais recente primeiro


# ── get_stats ──────────────────────────────────────────────────────────────

def test_stats_vazio(hm):
    stats = hm.get_stats()
    assert stats["total_plays"] == 0
    assert stats["top_clips"] == []


def test_stats_ranking(hm):
    for _ in range(3):
        _insert("2026-07-30", "Clip A", "/a.mp4", 60, "completed")
    _insert("2026-07-30", "Clip B", "/b.mp4", 120, "completed")

    stats = hm.get_stats()
    assert stats["total_plays"] == 4
    assert stats["top_clips"][0]["path"] == "/a.mp4"
    assert stats["top_clips"][0]["play_count"] == 3
    assert stats["top_clips"][1]["path"] == "/b.mp4"


def test_stats_total_horas(hm):
    _insert("2026-07-30", "A", "/a.mp4", 3600, "completed")  # 1 hora
    _insert("2026-07-30", "B", "/b.mp4", 1800, "completed")  # 0.5 hora

    stats = hm.get_stats()
    assert abs(stats["total_hours"] - 1.5) < 0.01


def test_stats_total_days(hm):
    _insert("2026-07-28", "A", "/a.mp4", 60, "completed")
    _insert("2026-07-29", "B", "/b.mp4", 60, "completed")
    _insert("2026-07-30", "C", "/c.mp4", 60, "completed")

    assert hm.get_stats()["total_days"] == 3
