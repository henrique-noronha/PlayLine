"""Configuração compartilhada dos testes — banco isolado por teste."""

import sys
from pathlib import Path

# Garante que backend/ está no sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import core.db as db


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    """Cada teste recebe um SQLite limpo e isolado."""
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()
    yield test_db
