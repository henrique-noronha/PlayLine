"""Testes de concorrência — duas escritas simultâneas no roteiro."""

import threading
from unittest.mock import MagicMock, AsyncMock

import pytest
from core.db import get_conn
from core.playlist import PlaylistEngine


@pytest.fixture
def engine():
    player = MagicMock()
    player.prefetch_yt = MagicMock()
    broadcast = AsyncMock()
    return PlaylistEngine(player=player, broadcast=broadcast)


def _make_items(prefix: str, count: int) -> list[dict]:
    return [
        {"id": f"{prefix}-{i}", "title": f"{prefix} Clip {i}",
         "path": f"C:\\{prefix}_{i}.mp4", "live": False}
        for i in range(count)
    ]


def test_duas_escritas_simultaneas_resultado_consistente(engine):
    """
    Duas threads salvam roteiros diferentes ao mesmo tempo.
    Após ambas terminarem, o banco deve conter exatamente
    um dos dois roteiros — nunca um mix dos dois.
    """
    roteiro_a = _make_items("A", 5)
    roteiro_b = _make_items("B", 5)
    ids_a = {it["id"] for it in roteiro_a}
    ids_b = {it["id"] for it in roteiro_b}

    barrier = threading.Barrier(2)
    errors = []

    def salvar(items):
        try:
            barrier.wait()  # as duas threads arrancam juntas
            engine.save_schedule(items)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=salvar, args=(roteiro_a,))
    t2 = threading.Thread(target=salvar, args=(roteiro_b,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Exceções durante escritas: {errors}"

    conn = get_conn()
    rows = conn.execute("SELECT id FROM schedule ORDER BY position").fetchall()
    conn.close()

    ids_resultado = {r["id"] for r in rows}

    # O resultado deve ser exatamente um dos dois roteiros, nunca uma mistura
    assert ids_resultado == ids_a or ids_resultado == ids_b, (
        f"Estado inconsistente — mix detectado: {ids_resultado}"
    )


def test_escrita_e_leitura_simultaneas_nao_retornam_estado_parcial(engine):
    """
    Uma thread escreve um roteiro de 10 itens enquanto outra lê continuamente.
    Nenhuma leitura deve retornar um estado parcial (0 < n < 10).
    """
    roteiro = _make_items("X", 10)
    engine.save_schedule(_make_items("INICIAL", 10))  # estado inicial

    leituras_parciais = []
    parar = threading.Event()

    def leitor():
        while not parar.is_set():
            conn = get_conn()
            count = conn.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
            conn.close()
            if count not in (0, 10):
                leituras_parciais.append(count)

    def escritor():
        for _ in range(20):
            engine.save_schedule(roteiro)

    t_leitura = threading.Thread(target=leitor)
    t_escrita  = threading.Thread(target=escritor)

    t_leitura.start()
    t_escrita.start()
    t_escrita.join()
    parar.set()
    t_leitura.join()

    assert not leituras_parciais, (
        f"Leituras com estado parcial detectadas: {leituras_parciais}"
    )


def test_checkpoint_escrita_concorrente(monkeypatch):
    """
    Daemon (thread 1) e servidor (thread 2) escrevem no checkpoint
    ao mesmo tempo — nenhum deve lançar exceção e o banco deve
    permanecer em estado válido (exatamente 1 linha).
    """
    from daemon import checkpoint
    from pathlib import Path

    import core.db as db
    monkeypatch.setattr(checkpoint, "_DB_PATH", db.DB_PATH)

    barrier = threading.Barrier(2)
    errors = []

    def daemon_write():
        try:
            barrier.wait()
            for i in range(10):
                checkpoint.write(Path("x"), f"C:\\clip_{i}.mp4")
                checkpoint.flush(Path("x"), float(i))
        except Exception as exc:
            errors.append(exc)

    def server_read():
        try:
            barrier.wait()
            for _ in range(10):
                conn = db.get_conn()
                conn.execute("SELECT * FROM checkpoint WHERE id=1").fetchone()
                conn.close()
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=daemon_write)
    t2 = threading.Thread(target=server_read)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Exceções durante acesso concorrente: {errors}"

    conn = db.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM checkpoint").fetchone()[0]
    conn.close()
    assert count == 1
