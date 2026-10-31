import logging
import os
import random
import time

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("mem0.db")


def _build_database_url() -> URL:
    """Build the DSN as a URL object instead of string interpolation.

    A password containing @ : / ? # or % would otherwise be parsed as URL
    delimiters: "p@ss" turns postgres:5432 into the host and the connection fails
    with a confusing "could not translate host name" error. URL.create()
    percent-encodes each component.
    """
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "postgres")
    db = os.environ.get("APP_DB_NAME", "mem0_app")
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=int(port),
        database=db,
    )


# create_engine is lazy: no connection is opened until the first connect() call,
# which happens in `alembic upgrade` or on the first request. So a database that
# is not up yet does not fail at import time, it fails in the entrypoint script
# and the container exits immediately.
engine = create_engine(_build_database_url(), pool_pre_ping=True, pool_recycle=1800)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def db_target() -> str:
    """Return the connection target without credentials, for startup logs."""
    url = make_url(engine.url)
    return f"{url.drivername}://{url.host}:{url.port}/{url.database}"


def wait_for_db(
    max_attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
) -> None:
    """Block until PostgreSQL accepts connections, with exponential backoff.

    Covers the "process started before its dependency" class of failures:
      - container name not registered in Docker's embedded DNS yet
        -> psycopg.OperationalError: failed to resolve host 'postgres'
      - PostgreSQL still replaying WAL after an unclean shutdown
        -> the database system is starting up
      - database briefly refusing connections after a restart
        -> Connection refused

    After max_attempts the last exception is re-raised so the container exits and
    the compose restart policy takes over, instead of serving traffic with an
    unusable connection pool.
    """
    attempts = max_attempts or int(os.environ.get("DB_CONNECT_MAX_ATTEMPTS", "30"))
    base = base_delay if base_delay is not None else float(os.environ.get("DB_CONNECT_BASE_DELAY", "0.5"))
    ceiling = max_delay if max_delay is not None else float(os.environ.get("DB_CONNECT_MAX_DELAY", "5"))

    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except DBAPIError as exc:
            if attempt >= attempts:
                logger.error("database still unavailable after %s attempts, giving up", attempts)
                raise
            delay = min(base * (2 ** (attempt - 1)), ceiling)
            delay *= 0.5 + random.random()  # jitter, avoid thundering herd on restart
            first_line = (str(exc).splitlines() or [""])[0][:200]
            logger.warning(
                "database unavailable (attempt %s/%s, target %s): %s; retrying in %.1fs",
                attempt,
                attempts,
                db_target(),
                first_line,
                delay,
            )
            time.sleep(delay)
        else:
            logger.info("database ready (attempt %s/%s, target %s)", attempt, attempts, db_target())
            return


def get_db():
    """FastAPI dependency that yields a SQLAlchemy session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
