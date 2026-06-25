"""Core test fixtures. Uses tmp DB and monkeypatches shilljudge_core.database.DB_PATH."""
import sys
from pathlib import Path

# Ensure src layout is on path when running pytest directly (pythonpath in pyproject also helps)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

import shilljudge_core.database as db_module
from shilljudge_core.database import init_db


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "core_test.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    # Also patch the module-level constant used by get_connection etc.
    init_db()
    # Pre-insert a user so FKs for posts/threads succeed in tests that create content
    with db_module.get_connection() as conn:
        conn.execute("INSERT INTO users (x_id, x_username) VALUES ('user1', 'testuser')")
    return db_file
