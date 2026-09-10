"""Reusable internal stock return transform."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from scripts.transform.audit import AuditResult, print_audit, run_audit_on_connection
from scripts.transform.context import validate_identifier
from scripts.transform.production_output import SOURCE_RECORD_TYPE, SOURCE_SYSTEM, read_production_csv


logger = logging.getLogger(__name__)

LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"


@dataclass(frozen=True)
class InternalStockReturnTransformResult:
    audit: AuditResult
    internal_stock_return_rows: int


def configure_transaction_guardrails(conn: Connection) -> None:
    lock_key = "internal_stock_return"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def create_temp_table(conn: Connection, df: pd.DataFrame) -> None:
    df.to_sql(
        "internal_stock_return_source",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    conn.execute(text('CREATE INDEX ON pg_temp.internal_stock_return_source ("source_record_type")'))
    conn.execute(text('CREATE INDEX ON pg_temp.internal_stock_return_source ("source_sku_code")'))
    conn.execute(text('CREATE INDEX ON pg_temp.internal_stock_return_source ("parsed_barcode")'))
    conn.execute(text('CREATE INDEX ON pg_temp.internal_stock_return_source ("source_product_label")'))
    conn.execute(text('CREATE INDEX ON pg_temp.internal_stock_return_source ("raw_record_id")'))
    conn.execute(text("ANALYZE pg_temp.internal_stock_return_source"))
    logger.info("Temporary internal return source table created: rows=%s", len(df))


def resolution_cte(target_schema: str) -> str:
    return f"""
source_rows AS (
    SELECT
        source_row_number::integer AS source_row_number,
        NULLIF(TRIM(source_record_type), '') AS source_return_type,
        NULLIF(TRIM(record_date_raw), '') AS record_date_raw,
        NULLIF(TRIM(production_date), '')::date AS return_date,
        NULLIF(TRIM(source_product_name), '') AS source_product_name,
        NULLIF(TRIM(source_product_label), '') AS source_product_label,
        NULLIF(TRIM(source_sku_code), '') AS source_sku_code,
        NULLIF(TRIM(parsed_barcode), '') AS parsed_barcode,
        NULLIF(TRIM(quantity_raw), '') AS quantity_raw,
        quantity_produced::numeric(18, 4) AS quantity_returned,
        NULLIF(TRIM(source_from_raw), '') AS source_from_raw,
        NULLIF(TRIM(source_box_raw), '') AS source_box_raw,
        NULLIF(TRIM(source_file), '') AS source_file,
        NULLIF(TRIM(source_sheet), '') AS source_sheet,
        NULLIF(TRIM(raw_record_id), '') AS raw_record_id
    FROM pg_temp.internal_stock_return_source
    WHERE NULLIF(TRIM(source_record_type), '') IS NOT NULL
      AND NULLIF(TRIM(source_record_type), '') <> '{SOURCE_RECORD_TYPE}'
),
pma_match AS (
    SELECT DISTINCT ON (sr.raw_record_id)
        sr.raw_record_id,
        pma.product_id,
        pma.product_sku_alias_id,
        'product_marketplace_alias.raw_alias' AS product_match_method
    FROM source_rows sr
    JOIN {target_schema}.product_marketplace_alias pma
      ON pma.is_active
     AND LOWER(pma.raw_alias) = LOWER(sr.source_sku_code)
    WHERE sr.source_sku_code IS NOT NULL
    ORDER BY sr.raw_record_id, pma.product_sku_alias_id
),
psa_token_match AS (
    SELECT DISTINCT ON (sr.raw_record_id)
        sr.raw_record_id,
        psa.product_id,
        psa.product_sku_alias_id,
        'product_sku_alias.sku_code' AS product_match_method
    FROM source_rows sr
    JOIN {target_schema}.product_sku_alias psa
      ON psa.is_active
     AND LOWER(psa.sku_code) = LOWER(sr.source_sku_code)
    WHERE sr.source_sku_code IS NOT NULL
    ORDER BY
        sr.raw_record_id,
        CASE WHEN psa.sales_channel_type = 'production' THEN 0 ELSE 1 END,
        CASE WHEN psa.source_system = 'accurate' THEN 0 ELSE 1 END,
        CASE WHEN psa.is_primary THEN 0 ELSE 1 END,
        psa.product_sku_alias_id
),
product_name_match AS (
    SELECT DISTINCT ON (sr.raw_record_id)
        sr.raw_record_id,
        dp.product_id,
        psa.product_sku_alias_id,
        'dim_product.product_name' AS product_match_method
    FROM source_rows sr
    JOIN {target_schema}.dim_product dp
      ON LOWER(REGEXP_REPLACE(dp.product_name, '[^a-zA-Z0-9]+', ' ', 'g')) =
         LOWER(REGEXP_REPLACE(sr.source_product_label, '[^a-zA-Z0-9]+', ' ', 'g'))
    LEFT JOIN {target_schema}.product_sku_alias psa
      ON psa.product_id = dp.product_id
     AND psa.is_active
    WHERE sr.source_product_label IS NOT NULL
    ORDER BY
        sr.raw_record_id,
        CASE WHEN psa.sales_channel_type = 'production' THEN 0 ELSE 1 END,
        CASE WHEN psa.source_system = 'accurate' THEN 0 ELSE 1 END,
        CASE WHEN psa.is_primary THEN 0 ELSE 1 END,
        psa.product_sku_alias_id
),
barcode_match AS (
    SELECT DISTINCT ON (sr.raw_record_id)
        sr.raw_record_id,
        psa.product_id,
        psa.product_sku_alias_id,
        'parsed_barcode_exact_when_source_token_is_barcode' AS product_match_method
    FROM source_rows sr
    JOIN {target_schema}.product_sku_alias psa
      ON psa.is_active
     AND LOWER(psa.sku_code) = LOWER(sr.parsed_barcode)
    WHERE sr.source_sku_code = sr.parsed_barcode
      AND sr.parsed_barcode IS NOT NULL
    ORDER BY
        sr.raw_record_id,
        CASE WHEN psa.sales_channel_type = 'production' THEN 0 ELSE 1 END,
        CASE WHEN psa.source_system = 'accurate' THEN 0 ELSE 1 END,
        CASE WHEN psa.is_primary THEN 0 ELSE 1 END,
        psa.product_sku_alias_id
),
resolved_rows AS (
    SELECT
        sr.*,
        COALESCE(pm.product_id, tm.product_id, nm.product_id, bm.product_id) AS product_id,
        COALESCE(
            pm.product_sku_alias_id,
            tm.product_sku_alias_id,
            nm.product_sku_alias_id,
            bm.product_sku_alias_id
        ) AS product_sku_alias_id,
        COALESCE(
            pm.product_match_method,
            tm.product_match_method,
            nm.product_match_method,
            bm.product_match_method,
            'unmatched'
        ) AS product_match_method
    FROM source_rows sr
    LEFT JOIN pma_match pm ON pm.raw_record_id = sr.raw_record_id
    LEFT JOIN psa_token_match tm ON tm.raw_record_id = sr.raw_record_id
    LEFT JOIN product_name_match nm ON nm.raw_record_id = sr.raw_record_id
    LEFT JOIN barcode_match bm ON bm.raw_record_id = sr.raw_record_id
)
"""


def audit_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)},
apparent_duplicate AS (
    SELECT
        source_return_type,
        return_date,
        source_product_name,
        COALESCE(source_from_raw, '') AS source_from_raw,
        COALESCE(source_box_raw, '') AS source_box_raw,
        COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY
        source_return_type,
        return_date,
        source_product_name,
        COALESCE(source_from_raw, ''),
        COALESCE(source_box_raw, '')
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Usable left-side rows from production CSV.' AS notes
FROM pg_temp.internal_stock_return_source
UNION ALL
SELECT 'internal_return_source_rows', COUNT(*)::bigint, 'Rows whose source_record_type is internal Return/Retur.'
FROM resolved_rows
UNION ALL
SELECT 'internal_return_insert_candidate_rows', COUNT(*)::bigint, 'Internal return rows with quantity > 0.'
FROM resolved_rows
WHERE quantity_returned > 0
UNION ALL
SELECT 'skipped_production_output_rows', COUNT(*)::bigint, 'Rows in same source file that represent production output, not internal return.'
FROM pg_temp.internal_stock_return_source
WHERE NULLIF(TRIM(source_record_type), '') = '{SOURCE_RECORD_TYPE}'
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Internal return rows that do not resolve to dim_product/product_sku_alias.'
FROM resolved_rows
WHERE product_id IS NULL
  AND COALESCE(quantity_returned, 0) <> 0
UNION ALL
SELECT 'invalid_date_rows', COUNT(*)::bigint, 'Internal return rows whose date could not be parsed.'
FROM resolved_rows
WHERE return_date IS NULL
UNION ALL
SELECT 'invalid_quantity_rows', COUNT(*)::bigint, 'Internal return rows whose quantity could not be parsed.'
FROM resolved_rows
WHERE quantity_returned IS NULL
UNION ALL
SELECT 'zero_quantity_rows', COUNT(*)::bigint, 'Internal return rows with quantity = 0.'
FROM resolved_rows
WHERE quantity_returned = 0
UNION ALL
SELECT 'duplicate_source_row_extra_rows', GREATEST(COUNT(*) - COUNT(DISTINCT raw_record_id), 0)::bigint, 'Duplicate raw_record_id rows in temp source.'
FROM resolved_rows
UNION ALL
SELECT 'apparent_duplicate_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra rows by type/date/product/from/box; retained as source lines.'
FROM apparent_duplicate
UNION ALL
SELECT 'existing_target_rows', COUNT(*)::bigint, 'Existing rows in fact_internal_stock_return for this source_system.'
FROM {target_schema}.fact_internal_stock_return
WHERE source_system = '{SOURCE_SYSTEM}';
"""


def insert_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
INSERT INTO {target_schema}.fact_internal_stock_return (
    source_system,
    source_return_type,
    return_date,
    return_datetime,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    quantity_returned,
    unit,
    warehouse_id,
    source_warehouse_name,
    source_from_raw,
    source_box_raw,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    notes,
    updated_at
)
SELECT
    '{SOURCE_SYSTEM}' AS source_system,
    source_return_type,
    return_date,
    NULL::timestamptz AS return_datetime,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    quantity_returned,
    'PCS' AS unit,
    NULL::integer AS warehouse_id,
    NULL::text AS source_warehouse_name,
    source_from_raw,
    source_box_raw,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    'Loaded by scripts/backfill/internal_stock_return_backfill.py; product_match_method=' || product_match_method AS notes,
    now() AS updated_at
FROM resolved_rows
WHERE product_id IS NOT NULL
  AND return_date IS NOT NULL
  AND quantity_returned IS NOT NULL
  AND quantity_returned > 0
ON CONFLICT (source_system, raw_record_id) DO UPDATE SET
    source_return_type = EXCLUDED.source_return_type,
    return_date = EXCLUDED.return_date,
    return_datetime = EXCLUDED.return_datetime,
    product_id = EXCLUDED.product_id,
    product_sku_alias_id = EXCLUDED.product_sku_alias_id,
    source_sku_code = EXCLUDED.source_sku_code,
    source_product_name = EXCLUDED.source_product_name,
    quantity_returned = EXCLUDED.quantity_returned,
    unit = EXCLUDED.unit,
    warehouse_id = EXCLUDED.warehouse_id,
    source_warehouse_name = EXCLUDED.source_warehouse_name,
    source_from_raw = EXCLUDED.source_from_raw,
    source_box_raw = EXCLUDED.source_box_raw,
    source_file = EXCLUDED.source_file,
    source_sheet = EXCLUDED.source_sheet,
    source_row_number = EXCLUDED.source_row_number,
    notes = EXCLUDED.notes,
    is_active = true,
    updated_at = now();
"""


def unmapped_products_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    source_return_type,
    source_sku_code,
    parsed_barcode,
    source_product_label,
    source_product_name,
    COUNT(*) AS row_count,
    MIN(source_row_number) AS first_source_row_number,
    MAX(source_row_number) AS last_source_row_number
FROM resolved_rows
WHERE product_id IS NULL
  AND COALESCE(quantity_returned, 0) <> 0
GROUP BY source_return_type, source_sku_code, parsed_barcode, source_product_label, source_product_name
ORDER BY row_count DESC, source_product_name;
"""


def duplicate_grain_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    source_return_type,
    return_date,
    source_sku_code,
    source_product_name,
    COALESCE(source_from_raw, '') AS source_from_raw,
    COALESCE(source_box_raw, '') AS source_box_raw,
    COUNT(*) AS row_count,
    COUNT(*) - 1 AS extra_rows,
    STRING_AGG(source_row_number::text, ', ' ORDER BY source_row_number) AS source_row_numbers
FROM resolved_rows
GROUP BY
    source_return_type,
    return_date,
    source_sku_code,
    source_product_name,
    COALESCE(source_from_raw, ''),
    COALESCE(source_box_raw, '')
HAVING COUNT(*) > 1
ORDER BY extra_rows DESC, return_date, source_return_type, source_product_name;
"""


def write_query_csv(conn: Connection, sql: str, output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    result = conn.execute(text(sql))
    rows = result.fetchall()
    columns = list(result.keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    return path


def run_internal_stock_return_transform(
    conn: Connection,
    *,
    source_df: pd.DataFrame,
    target_schema: str = "public",
    execute: bool = False,
    allow_unmapped: bool = False,
    export_unmapped_products: str | Path | None = None,
    export_duplicate_grain: str | Path | None = None,
) -> InternalStockReturnTransformResult:
    validate_identifier(target_schema, "target_schema")
    configure_transaction_guardrails(conn)
    create_temp_table(conn, source_df)

    try:
        logger.info("Run audit source_system=%s", SOURCE_SYSTEM)
        audit = run_audit_on_connection(conn, audit_sql(target_schema))
        print_audit(audit)

        if export_unmapped_products:
            write_query_csv(conn, unmapped_products_sql(target_schema), export_unmapped_products)
            logger.info("Unmapped product export: %s", Path(export_unmapped_products).resolve())

        if export_duplicate_grain:
            write_query_csv(conn, duplicate_grain_sql(target_schema), export_duplicate_grain)
            logger.info("Duplicate grain export: %s", Path(export_duplicate_grain).resolve())

        blocking_metrics = (
            audit.value("unmapped_product_rows"),
            audit.value("invalid_date_rows"),
            audit.value("invalid_quantity_rows"),
        )
        if any(value > 0 for value in blocking_metrics) and not allow_unmapped:
            raise RuntimeError(
                "Transform blocked: unmapped product, invalid date, or invalid quantity rows detected. "
                "Fix mapping/source first, or rerun with --allow-unmapped for controlled testing."
            )

        if not execute:
            logger.info("Dry-run only. Add --execute to insert into target fact.")
            return InternalStockReturnTransformResult(audit=audit, internal_stock_return_rows=0)

        logger.info("Execute transform source_system=%s", SOURCE_SYSTEM)
        insert_result = conn.execute(text(insert_sql(target_schema)))
        conn.execute(text(f"ANALYZE {target_schema}.fact_internal_stock_return"))
        logger.info("Internal stock return upsert finished: rows=%s", insert_result.rowcount)

        return InternalStockReturnTransformResult(
            audit=audit,
            internal_stock_return_rows=insert_result.rowcount,
        )
    finally:
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.internal_stock_return_source"))
