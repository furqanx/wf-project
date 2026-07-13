"""Raw staging table helpers for import scripts."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.config import TARGET_SCHEMA


def is_table_exists(engine: Engine, table_name: str, schema: str = TARGET_SCHEMA) -> bool:
    query = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_name = :table_name
        )
        """
    )
    with engine.connect() as conn:
        return bool(conn.execute(query, {"schema": schema, "table_name": table_name}).scalar())


def get_table_columns(engine: Engine, table_name: str, schema: str = TARGET_SCHEMA) -> list[str]:
    query = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema
          AND table_name = :table_name
        ORDER BY ordinal_position
        """
    )
    with engine.connect() as conn:
        return [row.column_name for row in conn.execute(query, {"schema": schema, "table_name": table_name})]


def append_dataframe_to_table(
    engine: Engine,
    df: pd.DataFrame,
    table_name: str,
    schema: str = TARGET_SCHEMA,
) -> int:
    """Append a DataFrame to a staging table using only columns that exist in the target."""
    if not is_table_exists(engine, table_name, schema=schema):
        raise RuntimeError(f"Target table not found: {schema}.{table_name}")

    table_columns = get_table_columns(engine, table_name, schema=schema)
    insert_columns = [column for column in df.columns if column in table_columns]
    if not insert_columns:
        raise RuntimeError(f"No matching columns for target table: {schema}.{table_name}")

    insert_df = df.loc[:, insert_columns].copy()
    insert_df.to_sql(
        table_name,
        engine,
        schema=schema,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )
    return len(insert_df)

