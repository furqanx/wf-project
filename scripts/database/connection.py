"""Database connection helpers for import scripts."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL

from scripts.config import DEFAULT_DB_NAME
from scripts.utils.env import get_env, load_dotenv_file


def build_database_url(database: str | None = None) -> URL:
    """Build a SQLAlchemy PostgreSQL URL from environment variables."""
    load_dotenv_file()
    target_database = database or get_env("IMPORT_DB_NAME", get_env("DB_NAME", DEFAULT_DB_NAME))

    return URL.create(
        drivername="postgresql+psycopg2",
        username=get_env("DB_USER", required=True),
        password=get_env("DB_PASSWORD", required=True),
        host=get_env("DB_HOST", required=True),
        port=int(get_env("DB_PORT", "5432") or "5432"),
        database=target_database,
        query={"sslmode": get_env("DB_SSLMODE", "require") or "require"},
    )


def get_engine(database: str | None = None) -> Engine:
    """Create a SQLAlchemy engine for the import target database."""
    return create_engine(build_database_url(database), pool_pre_ping=True)

