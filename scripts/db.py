"""Compatibility wrapper for database import helpers."""

from __future__ import annotations

from scripts.database.connection import build_database_url, get_engine
from scripts.database.staging import (
    append_dataframe_to_table,
    get_table_columns,
    is_table_exists,
)

__all__ = [
    "append_dataframe_to_table",
    "build_database_url",
    "get_engine",
    "get_table_columns",
    "is_table_exists",
]
