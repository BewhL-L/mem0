"""Wait for PostgreSQL before running migrations.

Compose entrypoint runs `python scripts/wait_for_db.py && alembic upgrade head`.
Without the wait, the very first connection happens inside `alembic upgrade`, where
a not-yet-ready database (container DNS not registered, crash recovery in progress)
surfaces as an unhandled OperationalError and the container exits immediately.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import db_target, wait_for_db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main() -> int:
    print(f"[wait_for_db] target={db_target()}", flush=True)
    wait_for_db()
    print("[wait_for_db] database is accepting connections", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
