"""Reusable production output transform."""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from scripts.transform.audit import AuditResult, print_audit, run_audit_on_connection
from scripts.transform.context import validate_identifier


logger = logging.getLogger(__name__)

LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"
SOURCE_SYSTEM = "manual_spreadsheet"
SOURCE_RECORD_TYPE = "Produksi Harian"
SKU_RE = re.compile(r"(\d{12,14})")


@dataclass(frozen=True)
class ProductionOutputTransformResult:
    audit: AuditResult
    production_output_rows: int


def is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def extract_source_sku_token(value: object) -> str:
    if is_blank(value):
        return ""
    return str(value).split("/", 1)[0].strip()


def extract_barcode(value: object) -> str:
    match = SKU_RE.search(str(value or ""))
    return match.group(1) if match else ""


def extract_product_label(value: object) -> str:
    if is_blank(value):
        return ""
    parts = str(value).split("/", 1)
    return parts[1].strip() if len(parts) > 1 else str(value).strip()


def read_production_csv(path: str | Path) -> pd.DataFrame:
    source_path = Path(path).expanduser().resolve()
    raw = pd.read_csv(
        source_path,
        header=None,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )

    left = raw.iloc[:, :6].copy()
    left.columns = [
        "source_record_type",
        "record_date_raw",
        "source_product_name",
        "quantity_raw",
        "source_from_raw",
        "source_box_raw",
    ]
    left["source_row_number"] = left.index + 1
    left = left[left["source_row_number"] > 2].copy()

    for column in left.columns:
        if column != "source_row_number":
            left[column] = left[column].astype(str).str.strip()

    left = left[
        (left["source_record_type"] != "")
        & (left["record_date_raw"] != "")
        & (left["source_product_name"] != "")
        & (left["quantity_raw"] != "")
    ].copy()

    parsed_dates = pd.to_datetime(
        left["record_date_raw"], format="%d-%b-%Y", errors="coerce"
    )
    left["production_date"] = parsed_dates.dt.strftime("%Y-%m-%d").fillna("")
    left["quantity_produced"] = pd.to_numeric(
        left["quantity_raw"].str.replace(",", "", regex=False), errors="coerce"
    )
    left["source_sku_code"] = left["source_product_name"].map(extract_source_sku_token)
    left["parsed_barcode"] = left["source_product_name"].map(extract_barcode)
    left["source_product_label"] = left["source_product_name"].map(extract_product_label)
    left["source_file"] = source_path.name
    left["source_sheet"] = "Produksi"
    left["raw_record_id"] = (
        SOURCE_SYSTEM
        + ":"
        + left["source_file"].astype(str)
        + ":"
        + left["source_row_number"].astype(str)
    )

    return left[
        [
            "source_row_number",
            "source_record_type",
            "record_date_raw",
            "production_date",
            "source_product_name",
            "source_product_label",
            "source_sku_code",
            "parsed_barcode",
            "quantity_raw",
            "quantity_produced",
            "source_from_raw",
            "source_box_raw",
            "source_file",
            "source_sheet",
            "raw_record_id",
        ]
    ]


def configure_transaction_guardrails(conn: Connection) -> None:
    lock_key = "production_output"
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
        "production_output_source",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    conn.execute(text('CREATE INDEX ON pg_temp.production_output_source ("source_record_type")'))
    conn.execute(text('CREATE INDEX ON pg_temp.production_output_source ("source_sku_code")'))
    conn.execute(text('CREATE INDEX ON pg_temp.production_output_source ("parsed_barcode")'))
    conn.execute(text('CREATE INDEX ON pg_temp.production_output_source ("source_product_label")'))
    conn.execute(text('CREATE INDEX ON pg_temp.production_output_source ("raw_record_id")'))
    conn.execute(text("ANALYZE pg_temp.production_output_source"))
    logger.info("Temporary production source table created: rows=%s", len(df))


def resolution_cte(target_schema: str) -> str:
    return f"""
source_rows AS (
    SELECT
        source_row_number::integer AS source_row_number,
        NULLIF(TRIM(source_record_type), '') AS source_record_type,
        NULLIF(TRIM(record_date_raw), '') AS record_date_raw,
        NULLIF(TRIM(production_date), '')::date AS production_date,
        NULLIF(TRIM(source_product_name), '') AS source_product_name,
        NULLIF(TRIM(source_product_label), '') AS source_product_label,
        NULLIF(TRIM(source_sku_code), '') AS source_sku_code,
        NULLIF(TRIM(parsed_barcode), '') AS parsed_barcode,
        NULLIF(TRIM(quantity_raw), '') AS quantity_raw,
        quantity_produced::numeric(18, 4) AS quantity_produced,
        NULLIF(TRIM(source_from_raw), '') AS source_from_raw,
        NULLIF(TRIM(source_box_raw), '') AS source_box_raw,
        NULLIF(TRIM(source_file), '') AS source_file,
        NULLIF(TRIM(source_sheet), '') AS source_sheet,
        NULLIF(TRIM(raw_record_id), '') AS raw_record_id
    FROM pg_temp.production_output_source
    WHERE NULLIF(TRIM(source_record_type), '') = '{SOURCE_RECORD_TYPE}'
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
        source_record_type,
        production_date,
        source_product_name,
        COALESCE(source_from_raw, '') AS source_from_raw,
        COALESCE(source_box_raw, '') AS source_box_raw,
        COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY
        source_record_type,
        production_date,
        source_product_name,
        COALESCE(source_from_raw, ''),
        COALESCE(source_box_raw, '')
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Usable left-side rows from production CSV.' AS notes
FROM pg_temp.production_output_source
UNION ALL
SELECT 'production_output_source_rows', COUNT(*)::bigint, 'Rows whose source_record_type is Produksi Harian.'
FROM resolved_rows
UNION ALL
SELECT 'skipped_internal_return_rows', COUNT(*)::bigint, 'Rows in same source file that represent internal returns, not production output.'
FROM pg_temp.production_output_source
WHERE NULLIF(TRIM(source_record_type), '') IS NOT NULL
  AND NULLIF(TRIM(source_record_type), '') <> '{SOURCE_RECORD_TYPE}'
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Production rows that do not resolve to dim_product/product_sku_alias.'
FROM resolved_rows
WHERE product_id IS NULL
UNION ALL
SELECT 'invalid_date_rows', COUNT(*)::bigint, 'Production rows whose date could not be parsed.'
FROM resolved_rows
WHERE production_date IS NULL
UNION ALL
SELECT 'invalid_quantity_rows', COUNT(*)::bigint, 'Production rows whose quantity could not be parsed.'
FROM resolved_rows
WHERE quantity_produced IS NULL
UNION ALL
SELECT 'zero_quantity_rows', COUNT(*)::bigint, 'Production rows with quantity = 0.'
FROM resolved_rows
WHERE quantity_produced = 0
UNION ALL
SELECT 'duplicate_source_row_extra_rows', GREATEST(COUNT(*) - COUNT(DISTINCT raw_record_id), 0)::bigint, 'Duplicate raw_record_id rows in temp source.'
FROM resolved_rows
UNION ALL
SELECT 'apparent_duplicate_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra rows by date/product/from/box; retained as source lines.'
FROM apparent_duplicate
UNION ALL
SELECT 'existing_target_rows', COUNT(*)::bigint, 'Existing rows in fact_production_output for this source_system.'
FROM {target_schema}.fact_production_output
WHERE source_system = '{SOURCE_SYSTEM}';
"""


def insert_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
INSERT INTO {target_schema}.fact_production_output (
    source_system,
    source_record_type,
    production_date,
    production_datetime,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    quantity_produced,
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
    source_record_type,
    production_date,
    NULL::timestamptz AS production_datetime,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    quantity_produced,
    'PCS' AS unit,
    NULL::integer AS warehouse_id,
    NULL::text AS source_warehouse_name,
    source_from_raw,
    source_box_raw,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    'Loaded by scripts/backfill/production_output_backfill.py; product_match_method=' || product_match_method AS notes,
    now() AS updated_at
FROM resolved_rows
WHERE product_id IS NOT NULL
  AND production_date IS NOT NULL
  AND quantity_produced IS NOT NULL
ON CONFLICT (source_system, raw_record_id) DO UPDATE SET
    source_record_type = EXCLUDED.source_record_type,
    production_date = EXCLUDED.production_date,
    production_datetime = EXCLUDED.production_datetime,
    product_id = EXCLUDED.product_id,
    product_sku_alias_id = EXCLUDED.product_sku_alias_id,
    source_sku_code = EXCLUDED.source_sku_code,
    source_product_name = EXCLUDED.source_product_name,
    quantity_produced = EXCLUDED.quantity_produced,
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
    source_sku_code,
    parsed_barcode,
    source_product_label,
    source_product_name,
    COUNT(*) AS row_count,
    MIN(source_row_number) AS first_source_row_number,
    MAX(source_row_number) AS last_source_row_number
FROM resolved_rows
WHERE product_id IS NULL
GROUP BY source_sku_code, parsed_barcode, source_product_label, source_product_name
ORDER BY row_count DESC, source_product_name;
"""


def duplicate_grain_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    production_date,
    source_sku_code,
    source_product_name,
    COALESCE(source_from_raw, '') AS source_from_raw,
    COALESCE(source_box_raw, '') AS source_box_raw,
    COUNT(*) AS row_count,
    COUNT(*) - 1 AS extra_rows,
    STRING_AGG(source_row_number::text, ', ' ORDER BY source_row_number) AS source_row_numbers
FROM resolved_rows
GROUP BY
    production_date,
    source_sku_code,
    source_product_name,
    COALESCE(source_from_raw, ''),
    COALESCE(source_box_raw, '')
HAVING COUNT(*) > 1
ORDER BY extra_rows DESC, production_date, source_product_name;
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


def run_production_output_transform(
    conn: Connection,
    *,
    source_df: pd.DataFrame,
    target_schema: str = "public",
    execute: bool = False,
    allow_unmapped: bool = False,
    export_unmapped_products: str | Path | None = None,
    export_duplicate_grain: str | Path | None = None,
) -> ProductionOutputTransformResult:
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
            return ProductionOutputTransformResult(audit=audit, production_output_rows=0)

        logger.info("Execute transform source_system=%s", SOURCE_SYSTEM)
        insert_result = conn.execute(text(insert_sql(target_schema)))
        conn.execute(text(f"ANALYZE {target_schema}.fact_production_output"))
        logger.info("Production output upsert finished: rows=%s", insert_result.rowcount)

        return ProductionOutputTransformResult(
            audit=audit,
            production_output_rows=insert_result.rowcount,
        )
    finally:
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.production_output_source"))
