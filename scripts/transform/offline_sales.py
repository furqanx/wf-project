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
    target_source_orders: int = 0
    missing_source_orders: int = 0


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
    export_missing_orders: str | Path | None = None,
    export_missing_items: str | Path | None = None,
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

        completeness = conn.execute(text(order_completeness_sql(ctx))).mappings().one()
        target_source_orders = int(completeness["target_source_orders"])
        missing_source_orders = int(completeness["missing_source_orders"])

        logger.info(
            "Offline DO order completeness: source_orders=%s target_source_orders=%s missing_source_orders=%s",
            completeness["source_orders"],
            target_source_orders,
            missing_source_orders,
        )

        if export_missing_orders:
            write_query_csv(conn, missing_orders_sql(ctx), export_missing_orders)
            logger.info("Missing order export: %s", Path(export_missing_orders).resolve())

        if export_missing_items:
            write_query_csv(conn, missing_items_sql(ctx), export_missing_items)
            logger.info("Missing item export: %s", Path(export_missing_items).resolve())

        if missing_source_orders > 0:
            raise RuntimeError(
                "Offline DO completeness check failed: some source DO orders are not present in "
                f"{target_schema}.fact_sales_order. Export missing rows with --export-missing-orders."
            )

        return OfflineDOTransformResult(
            audit=audit,
            order_rows=order_result.rowcount,
            item_rows=item_result.rowcount,
            target_source_orders=target_source_orders,
            missing_source_orders=missing_source_orders,
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


def order_completeness_sql(ctx: TransformContext) -> str:
    return f"""
WITH source_rows AS (
    SELECT DISTINCT
        NULLIF(NULLIF(NULLIF(TRIM(h.do_number), ''), 'nan'), '-') AS external_order_id,
        CASE
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'offline' THEN 'offline'
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'online' THEN 'online'
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'sample' THEN 'sample'
            ELSE COALESCE(LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')), 'offline')
        END AS sales_channel_type,
        dbp.b2b_partner_id
    FROM {ctx.staging_schema}.offline_do_header h
    JOIN {ctx.target_schema}.dim_b2b_partner dbp
        ON dbp.b2b_partner_id::text = NULLIF(NULLIF(NULLIF(TRIM(h.b2b_partner_id), ''), 'nan'), '-')
    WHERE NULLIF(NULLIF(NULLIF(TRIM(h.do_number), ''), 'nan'), '-') IS NOT NULL
),
matched_rows AS (
    SELECT s.*
    FROM source_rows s
    JOIN {ctx.target_schema}.fact_sales_order fso
        ON fso.source_system = 'offline_do'
       AND fso.sales_channel_type = s.sales_channel_type
       AND fso.external_order_id = s.external_order_id
       AND fso.b2b_partner_id = s.b2b_partner_id
)
SELECT
    COUNT(*)::bigint AS source_orders,
    COUNT(m.*)::bigint AS target_source_orders,
    (COUNT(*) - COUNT(m.*))::bigint AS missing_source_orders
FROM source_rows s
LEFT JOIN matched_rows m
    ON m.external_order_id = s.external_order_id
   AND m.sales_channel_type = s.sales_channel_type
   AND m.b2b_partner_id = s.b2b_partner_id;
"""


def missing_orders_sql(ctx: TransformContext) -> str:
    return f"""
WITH source_rows AS (
    SELECT DISTINCT
        NULLIF(NULLIF(NULLIF(TRIM(h.do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(h.customer_name), ''), 'nan'), '-') AS customer_name,
        NULLIF(NULLIF(NULLIF(TRIM(h.b2b_partner_id), ''), 'nan'), '-') AS source_b2b_partner_id,
        CASE
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'offline' THEN 'offline'
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'online' THEN 'online'
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'sample' THEN 'sample'
            ELSE COALESCE(LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')), 'offline')
        END AS sales_channel_type,
        NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-') AS raw_channel,
        NULLIF(NULLIF(NULLIF(TRIM(h.do_type), ''), 'nan'), '-') AS do_type,
        NULLIF(NULLIF(NULLIF(TRIM(h.invoice_number), ''), 'nan'), '-') AS external_invoice_id,
        h.source_filename,
        dbp.b2b_partner_id
    FROM {ctx.staging_schema}.offline_do_header h
    JOIN {ctx.target_schema}.dim_b2b_partner dbp
        ON dbp.b2b_partner_id::text = NULLIF(NULLIF(NULLIF(TRIM(h.b2b_partner_id), ''), 'nan'), '-')
    WHERE NULLIF(NULLIF(NULLIF(TRIM(h.do_number), ''), 'nan'), '-') IS NOT NULL
)
SELECT
    s.external_order_id,
    s.customer_name,
    s.source_b2b_partner_id,
    s.b2b_partner_id,
    s.sales_channel_type,
    s.raw_channel,
    s.do_type,
    s.external_invoice_id,
    s.source_filename
FROM source_rows s
LEFT JOIN {ctx.target_schema}.fact_sales_order fso
    ON fso.source_system = 'offline_do'
   AND fso.sales_channel_type = s.sales_channel_type
   AND fso.external_order_id = s.external_order_id
   AND fso.b2b_partner_id = s.b2b_partner_id
WHERE fso.sales_order_id IS NULL
ORDER BY s.sales_channel_type, s.external_order_id
LIMIT 5000;
"""


def missing_items_sql(ctx: TransformContext) -> str:
    return f"""
WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(i.item_id), ''), 'nan'), '-') AS source_line_id,
        NULLIF(NULLIF(NULLIF(TRIM(i.do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(i.sku), ''), 'nan'), '-') AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(i.product_name_raw), ''), 'nan'), '-') AS source_product_name,
        CASE
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'offline' THEN 'offline'
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'online' THEN 'online'
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')) = 'sample' THEN 'sample'
            ELSE COALESCE(LOWER(NULLIF(NULLIF(NULLIF(TRIM(h.channel), ''), 'nan'), '-')), 'offline')
        END AS sales_channel_type,
        dbp.b2b_partner_id,
        psa.product_sku_alias_id
    FROM {ctx.staging_schema}.offline_do_item i
    JOIN {ctx.staging_schema}.offline_do_header h
        ON NULLIF(NULLIF(NULLIF(TRIM(h.do_number), ''), 'nan'), '-')
         = NULLIF(NULLIF(NULLIF(TRIM(i.do_number), ''), 'nan'), '-')
    JOIN {ctx.target_schema}.dim_b2b_partner dbp
        ON dbp.b2b_partner_id::text = NULLIF(NULLIF(NULLIF(TRIM(h.b2b_partner_id), ''), 'nan'), '-')
    LEFT JOIN {ctx.target_schema}.product_sku_alias psa
        ON LOWER(psa.sku_code) = LOWER(NULLIF(NULLIF(NULLIF(TRIM(i.sku), ''), 'nan'), '-'))
       AND psa.is_active
    WHERE NULLIF(NULLIF(NULLIF(TRIM(i.do_number), ''), 'nan'), '-') IS NOT NULL
)
SELECT
    s.external_order_id,
    s.source_line_id,
    s.source_sku_code,
    s.source_product_name,
    s.sales_channel_type,
    s.b2b_partner_id,
    CASE
        WHEN s.product_sku_alias_id IS NULL THEN 'unmapped_product'
        WHEN fso.sales_order_id IS NULL THEN 'missing_order_header'
        ELSE 'missing_item'
    END AS missing_reason
FROM source_rows s
LEFT JOIN {ctx.target_schema}.fact_sales_order fso
    ON fso.source_system = 'offline_do'
   AND fso.sales_channel_type = s.sales_channel_type
   AND fso.external_order_id = s.external_order_id
   AND fso.b2b_partner_id = s.b2b_partner_id
LEFT JOIN {ctx.target_schema}.fact_sales_order_item fsoi
    ON fsoi.sales_order_id = fso.sales_order_id
   AND COALESCE(fsoi.source_line_id, '') = COALESCE(s.source_line_id, '')
   AND COALESCE(fsoi.source_sku_code, '') = COALESCE(s.source_sku_code, '')
WHERE s.product_sku_alias_id IS NULL
   OR fso.sales_order_id IS NULL
   OR fsoi.sales_order_item_id IS NULL
ORDER BY missing_reason, s.external_order_id, s.source_line_id
LIMIT 10000;
"""
