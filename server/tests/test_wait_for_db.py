"""Regression tests for the startup database wait loop (server/db.py).

No database is needed: engine.connect is replaced by a stub, so the tests only
assert the retry contract that keeps container startup alive when PostgreSQL is
not ready yet (container DNS not registered, crash recovery in progress).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402


def _conn_ok() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    return conn


def _operational_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("failed to resolve host 'postgres'"))


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """Never sleep, and keep log output free of a real engine.url lookup."""
    monkeypatch.setattr(db.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(db, "db_target", lambda: "postgresql+psycopg://postgres:5432/test")


def test_returns_after_first_success(monkeypatch):
    engine = MagicMock()
    engine.connect.return_value = _conn_ok()
    monkeypatch.setattr(db, "engine", engine)

    db.wait_for_db(max_attempts=3)

    assert engine.connect.call_count == 1


def test_retries_then_raises(monkeypatch):
    engine = MagicMock()

    def _always_fails():
        raise _operational_error()

    engine.connect.side_effect = _always_fails
    monkeypatch.setattr(db, "engine", engine)

    with pytest.raises(OperationalError):
        db.wait_for_db(max_attempts=3)

    assert engine.connect.call_count == 3


def test_succeeds_after_transient_failures(monkeypatch):
    engine = MagicMock()
    engine.connect.side_effect = [_operational_error(), _operational_error(), _conn_ok()]
    monkeypatch.setattr(db, "engine", engine)

    db.wait_for_db(max_attempts=5)

    assert engine.connect.call_count == 3


def test_dsn_is_plain_string_with_encoded_password(monkeypatch):
    """alembic calls config.set_main_option() with this value, which rejects non-str."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd")

    dsn = db._build_database_url()

    assert isinstance(dsn, str)
    assert "p%40ss%3Aw%2Frd" in dsn
    assert dsn.endswith("@postgres:5432/mem0_app")

