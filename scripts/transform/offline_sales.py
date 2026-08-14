"""Reusable offline sales transforms for phase-1 sales facts."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from scripts.transform.audit import AuditResult, print_audit, run_audit_on_connection
from scripts.transform.context import TransformContext


logger = logging.getLogger(__name__)

LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"


@dataclass(frozen=True)
class OfflineDOBackfillInput:
    header_csv: Path
    item_csv: Path
    target_schema: str = "public"


@dataclass(frozen=True)
class OfflineDOTransformResult:
    audit: AuditResult
    order_rows: int
    item_rows: int


def read_legacy_do_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(
        Path(path),
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )


def create_offline_do_temp_tables(
    conn: Connection,
    *,
    header_df: pd.DataFrame,
    item_df: pd.DataFrame,
) -> None:
    header_df.to_sql(
        "offline_do_header",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    item_df.to_sql(
        "offline_do_item",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )

    conn.execute(text('CREATE INDEX ON pg_temp.offline_do_header ("do_number")'))
    conn.execute(text('CREATE INDEX ON pg_temp.offline_do_header ("b2b_partner_id")'))
    conn.execute(text('CREATE INDEX ON pg_temp.offline_do_item ("do_number")'))
    conn.execute(text('CREATE INDEX ON pg_temp.offline_do_item ("sku")'))
    conn.execute(text("ANALYZE pg_temp.offline_do_header"))
    conn.execute(text("ANALYZE pg_temp.offline_do_item"))

    logger.info(
        "Temporary offline DO staging tables created: header_rows=%s item_rows=%s",
        len(header_df),
        len(item_df),
    )


def configure_transaction_guardrails(conn: Connection) -> None:
    lock_key = "sales_phase_1:offline_do"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def run_offline_do_transform(
    conn: Connection,
    *,
    header_df: pd.DataFrame,
    item_df: pd.DataFrame,
    target_schema: str = "public",
    execute: bool = False,
    allow_unmapped: bool = False,
    export_unmapped_products: str | Path | None = None,
    export_unmapped_partners: str | Path | None = None,
) -> OfflineDOTransformResult:
    ctx = TransformContext(staging_schema="pg_temp", target_schema=target_schema)
    configure_transaction_guardrails(conn)
    create_offline_do_temp_tables(conn, header_df=header_df, item_df=item_df)

    audit_sql = ctx.render_sql("sales_order_offline_do_audit.sql")
    order_sql = ctx.render_sql("sales_order_offline_do_insert.sql")
    item_sql = ctx.render_sql("sales_order_item_offline_do_insert.sql")

    try:
        logger.info("Run audit source_system=offline_do")
        audit = run_audit_on_connection(conn, audit_sql)
        print_audit(audit)

        if export_unmapped_products:
            write_query_csv(conn, unmapped_products_sql(ctx), export_unmapped_products)
            logger.info("Unmapped product export: %s", Path(export_unmapped_products).resolve())

        if export_unmapped_partners:
            write_query_csv(conn, unmapped_partners_sql(ctx), export_unmapped_partners)
            logger.info("Unmapped partner export: %s", Path(export_unmapped_partners).resolve())

        blocking_metrics = (
            audit.value("unmapped_partner_rows"),
            audit.value("unmapped_product_rows"),
            audit.value("item_without_header_rows"),
        )
        if any(value > 0 for value in blocking_metrics) and not allow_unmapped:
            raise RuntimeError(
                "Transform blocked: unmapped partner/product rows or item rows without header detected. "
                "Fix mappings first, or rerun with --allow-unmapped for controlled testing."
            )

        if not execute:
            logger.info("Dry-run only. Add --execute to insert into target facts.")
            return OfflineDOTransformResult(audit=audit, order_rows=0, item_rows=0)

        logger.info("Execute transform source_system=offline_do")
        logger.info("Insert offline DO order rows")
        order_result = conn.execute(text(order_sql))
        logger.info("Insert offline DO order rows done: %s", order_result.rowcount)
        conn.execute(text(f"ANALYZE {target_schema}.fact_sales_order"))

        logger.info("Insert offline DO item rows")
        item_result = conn.execute(text(item_sql))
        logger.info("Insert offline DO item rows done: %s", item_result.rowcount)

        return OfflineDOTransformResult(
            audit=audit,
            order_rows=order_result.rowcount,
            item_rows=item_result.rowcount,
        )
    finally:
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.offline_do_header"))
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.offline_do_item"))


def write_query_csv(conn: Connection, sql: str, output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    result = conn.execute(text(sql))
    rows = result.fetchall()
    columns = list(result.keys())

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    return path


def unmapped_products_sql(ctx: TransformContext) -> str:
    return f"""
WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(sku), ''), 'nan'), '-') AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(product_name_raw), ''), 'nan'), '-') AS source_product_name,
        source_filename
    FROM {ctx.staging_schema}.offline_do_item
),
resolved_rows AS (
    SELECT
        s.*,
        psa.product_sku_alias_id
    FROM source_rows s
    LEFT JOIN {ctx.target_schema}.product_sku_alias psa
        ON LOWER(psa.sku_code) = LOWER(s.source_sku_code)
       AND psa.is_active
    WHERE s.external_order_id IS NOT NULL
)
SELECT
    source_sku_code,
    COUNT(*) AS row_count,
    COUNT(DISTINCT external_order_id) AS order_count,
    STRING_AGG(DISTINCT source_product_name, ' | ' ORDER BY source_product_name) AS sample_product_names,
    STRING_AGG(DISTINCT source_filename, ' | ' ORDER BY source_filename) AS sample_source_files
FROM resolved_rows
WHERE source_sku_code IS NOT NULL
  AND product_sku_alias_id IS NULL
GROUP BY source_sku_code
ORDER BY row_count DESC, source_sku_code
LIMIT 300;
"""


def unmapped_partners_sql(ctx: TransformContext) -> str:
    return f"""
WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(customer_name), ''), 'nan'), '-') AS customer_name,
        NULLIF(NULLIF(NULLIF(TRIM(b2b_partner_id), ''), 'nan'), '-') AS source_b2b_partner_id,
        source_filename
    FROM {ctx.staging_schema}.offline_do_header
),
resolved_rows AS (
    SELECT
        s.*,
        dbp.b2b_partner_id
    FROM source_rows s
    LEFT JOIN {ctx.target_schema}.dim_b2b_partner dbp
        ON dbp.b2b_partner_id::text = s.source_b2b_partner_id
    WHERE s.external_order_id IS NOT NULL
)
SELECT
    source_b2b_partner_id,
    customer_name,
    COUNT(*) AS row_count,
    STRING_AGG(DISTINCT source_filename, ' | ' ORDER BY source_filename) AS sample_source_files
FROM resolved_rows
WHERE source_b2b_partner_id IS NOT NULL
  AND b2b_partner_id IS NULL
GROUP BY source_b2b_partner_id, customer_name
ORDER BY row_count DESC, source_b2b_partner_id
LIMIT 300;
"""
