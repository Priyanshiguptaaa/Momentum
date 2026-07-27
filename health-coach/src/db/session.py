"""SQLAlchemy session and engine helpers."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.db.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str | None = None):
    database_url = url or settings.database_url
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(url: str | None = None) -> None:
    """Create all tables. Used by bootstrap and tests."""
    from sqlalchemy import inspect, text

    from src.db import models  # noqa: F401

    target_engine = _make_engine(url) if url else engine
    Base.metadata.create_all(bind=target_engine)

    # Lightweight SQLite column adds for existing DBs (no Alembic yet).
    if str(target_engine.url).startswith("sqlite"):
        with target_engine.begin() as conn:
            inspector = inspect(conn)
            if "users" in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns("users")}
                if "calorie_target" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN calorie_target FLOAT"))
            if "food_staples" in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns("food_staples")}
                if "learned_profile" not in cols:
                    conn.execute(text("ALTER TABLE food_staples ADD COLUMN learned_profile JSON"))
                if "times_logged" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE food_staples ADD COLUMN times_logged INTEGER DEFAULT 0"
                        )
                    )
