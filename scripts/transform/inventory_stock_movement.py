"""Reusable inventory stock movement transform."""

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
SOURCE_SYSTEM = "legacy_wellfarm"
SKU_RE = re.compile(r"(\d{12,14})")


@dataclass(frozen=True)
class InventoryStockMovementTransformResult:
    audit: AuditResult
    inventory_stock_movement_rows: int


def is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def normalize_text(value: object) -> str:
    text_value = str(value or "").strip().lower()
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


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


def parse_yyyymmdd(value: object) -> str:
    text_value = str(value or "").strip()
    parsed = pd.to_datetime(text_value, format="%Y%m%d", errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def classify_movement_subtype(row: pd.Series) -> str:
    combined = normalize_text(
        " ".join(
            [
                str(row.get("customer_name_raw") or ""),
                str(row.get("do_number") or ""),
                str(row.get("expedisi") or ""),
                str(row.get("invoice_number") or ""),
            ]
        )
    )
    if any(token in combined for token in ["marketplace", "shopee", "tokopedia", "lazada", "tiktok"]):
        return "marketplace"
    if any(token in combined for token in ["gudang", "warehouse", "dc jogja", "wellfarm jogja", "owellness"]):
        return "warehouse_transfer"
    if "sample" in combined:
        return "sample"
    if str(row.get("b2b_partner_id") or "").strip():
        return "b2b_distribution"
    return "stock_out"


def read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(
        Path(path).expanduser().resolve(),
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )


def build_source_df(source_csv: str | Path) -> pd.DataFrame:
    source_path = Path(source_csv).expanduser().resolve()
    df = read_csv(source_path).copy()
    for column in df.columns:
        df[column] = df[column].astype(str).str.strip()

    df["source_system"] = SOURCE_SYSTEM
    df["movement_type"] = "stock_out"
    df["movement_subtype"] = df.apply(classify_movement_subtype, axis=1)
    df["movement_date"] = df["ship_date_id"].map(parse_yyyymmdd)
    df["source_stock_out_id"] = df["stock_out_id"]
    df["source_product_id"] = df["product_id"]
    df["source_product_name"] = df["product_name_raw"]
    df["source_product_name_normalized"] = df["source_product_name"].map(normalize_text)
    df["source_sku_code"] = df["source_product_name"].map(extract_source_sku_token)
    df["parsed_barcode"] = df["source_product_name"].map(extract_barcode)
    df["source_product_label"] = df["source_product_name"].map(extract_product_label)
    df["source_product_label_normalized"] = df["source_product_label"].map(normalize_text)
    df["source_b2b_partner_id"] = df["b2b_partner_id"]
    df["source_customer_name"] = df["customer_name_raw"]
    df["source_customer_name_normalized"] = df["source_customer_name"].map(normalize_text)
    df["source_do_number"] = df["do_number"]
    df["source_invoice_number"] = df["invoice_number"]
    df["source_cargo_number"] = df["cargo_number"]
    df["source_expedisi"] = df["expedisi"]
    df["quantity"] = pd.to_numeric(df["qty_ordered"].str.replace(",", "", regex=False), errors="coerce")
    df["source_quantity_ordered"] = df["quantity"]
    df["source_quantity_shipped"] = pd.to_numeric(
        df["qty_shipped"].str.replace(",", "", regex=False), errors="coerce"
    )
    df["source_quantity_raw"] = df["qty_ordered"]
    df["source_file"] = df["source_filename"].replace("", source_path.name)
    df["source_sheet"] = "fact_stock_out"
    df["source_row_number"] = df.index + 2
    df["raw_record_id"] = (
        SOURCE_SYSTEM
        + ":"
        + df["source_file"].astype(str)
        + ":stock_out:"
        + df["source_stock_out_id"].astype(str)
    )

    return df[
        [
            "source_system",
            "movement_type",
            "movement_subtype",
            "movement_date",
            "source_stock_out_id",
            "source_product_id",
            "source_sku_code",
            "parsed_barcode",
            "source_product_name",
            "source_product_name_normalized",
            "source_product_label",
            "source_product_label_normalized",
            "source_b2b_partner_id",
            "source_customer_name",
            "source_customer_name_normalized",
            "source_do_number",
            "source_invoice_number",
            "source_cargo_number",
            "source_expedisi",
            "quantity",
            "source_quantity_ordered",
            "source_quantity_shipped",
            "source_quantity_raw",
            "notes",
            "source_file",
            "source_sheet",
            "source_row_number",
            "raw_record_id",
        ]
    ].rename(columns={"notes": "source_notes"})


def configure_transaction_guardrails(conn: Connection) -> None:
    lock_key = "inventory_stock_movement"
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
        "inventory_stock_movement_source",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    conn.execute(text('CREATE INDEX ON pg_temp.inventory_stock_movement_source ("raw_record_id")'))
    conn.execute(text('CREATE INDEX ON pg_temp.inventory_stock_movement_source ("source_sku_code")'))
    conn.execute(text('CREATE INDEX ON pg_temp.inventory_stock_movement_source ("parsed_barcode")'))
    conn.execute(text('CREATE INDEX ON pg_temp.inventory_stock_movement_source ("source_product_label_normalized")'))
    conn.execute(text('CREATE INDEX ON pg_temp.inventory_stock_movement_source ("source_b2b_partner_id")'))
    conn.execute(text('CREATE INDEX ON pg_temp.inventory_stock_movement_source ("quantity")'))
    conn.execute(text("ANALYZE pg_temp.inventory_stock_movement_source"))
    logger.info("Temporary inventory stock movement source table created: rows=%s", len(df))


def resolution_cte(target_schema: str) -> str:
    return f"""
source_rows AS (
    SELECT
        NULLIF(TRIM(source_system), '') AS source_system,
        NULLIF(TRIM(movement_type), '') AS movement_type,
        NULLIF(TRIM(movement_subtype), '') AS movement_subtype,
        NULLIF(TRIM(movement_date), '')::date AS movement_date,
        NULLIF(TRIM(source_stock_out_id), '') AS source_stock_out_id,
        NULLIF(TRIM(source_product_id), '') AS source_product_id,
        NULLIF(TRIM(source_sku_code), '') AS source_sku_code,
        NULLIF(TRIM(parsed_barcode), '') AS parsed_barcode,
        NULLIF(TRIM(source_product_name), '') AS source_product_name,
        NULLIF(TRIM(source_product_name_normalized), '') AS source_product_name_normalized,
        NULLIF(TRIM(source_product_label), '') AS source_product_label,
        NULLIF(TRIM(source_product_label_normalized), '') AS source_product_label_normalized,
        NULLIF(TRIM(source_b2b_partner_id), '') AS source_b2b_partner_id,
        NULLIF(TRIM(source_customer_name), '') AS source_customer_name,
        NULLIF(TRIM(source_customer_name_normalized), '') AS source_customer_name_normalized,
        NULLIF(TRIM(source_do_number), '') AS source_do_number,
        NULLIF(TRIM(source_invoice_number), '') AS source_invoice_number,
        NULLIF(TRIM(source_cargo_number), '') AS source_cargo_number,
        NULLIF(TRIM(source_expedisi), '') AS source_expedisi,
        quantity::numeric(18, 4) AS quantity,
        source_quantity_ordered::numeric(18, 4) AS source_quantity_ordered,
        source_quantity_shipped::numeric(18, 4) AS source_quantity_shipped,
        NULLIF(TRIM(source_quantity_raw), '') AS source_quantity_raw,
        NULLIF(TRIM(source_notes), '') AS source_notes,
        NULLIF(TRIM(source_file), '') AS source_file,
        NULLIF(TRIM(source_sheet), '') AS source_sheet,
        source_row_number::integer AS source_row_number,
        NULLIF(TRIM(raw_record_id), '') AS raw_record_id
    FROM pg_temp.inventory_stock_movement_source
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
partner_id_match AS (
    SELECT DISTINCT ON (sr.raw_record_id)
        sr.raw_record_id,
        dbp.b2b_partner_id,
        'dim_b2b_partner.b2b_partner_id' AS b2b_partner_match_method
    FROM source_rows sr
    JOIN {target_schema}.dim_b2b_partner dbp
      ON dbp.is_active
     AND dbp.b2b_partner_id::text = sr.source_b2b_partner_id
    WHERE sr.source_b2b_partner_id IS NOT NULL
    ORDER BY sr.raw_record_id, dbp.b2b_partner_id
),
partner_name_match AS (
    SELECT DISTINCT ON (sr.raw_record_id)
        sr.raw_record_id,
        dbp.b2b_partner_id,
        'dim_b2b_partner.partner_name_normalized' AS b2b_partner_match_method
    FROM source_rows sr
    JOIN {target_schema}.dim_b2b_partner dbp
      ON dbp.is_active
     AND dbp.partner_name_normalized = sr.source_customer_name_normalized
    WHERE sr.source_customer_name_normalized IS NOT NULL
    ORDER BY sr.raw_record_id, dbp.b2b_partner_id
),
resolved_rows AS (
    SELECT
        sr.*,
        COALESCE(pm.product_id, tm.product_id, bm.product_id, nm.product_id) AS product_id,
        COALESCE(pm.product_sku_alias_id, tm.product_sku_alias_id, bm.product_sku_alias_id, nm.product_sku_alias_id) AS product_sku_alias_id,
        COALESCE(pm.product_match_method, tm.product_match_method, bm.product_match_method, nm.product_match_method, 'unmatched') AS product_match_method,
        COALESCE(pim.b2b_partner_id, pnm.b2b_partner_id) AS b2b_partner_id,
        COALESCE(
            pim.b2b_partner_match_method,
            pnm.b2b_partner_match_method,
            CASE WHEN sr.source_b2b_partner_id IS NULL AND sr.source_customer_name_normalized IS NULL THEN 'not_provided' ELSE 'unmatched' END
        ) AS b2b_partner_match_method
    FROM source_rows sr
    LEFT JOIN pma_match pm ON pm.raw_record_id = sr.raw_record_id
    LEFT JOIN psa_token_match tm ON tm.raw_record_id = sr.raw_record_id
    LEFT JOIN barcode_match bm ON bm.raw_record_id = sr.raw_record_id
    LEFT JOIN product_name_match nm ON nm.raw_record_id = sr.raw_record_id
    LEFT JOIN partner_id_match pim ON pim.raw_record_id = sr.raw_record_id
    LEFT JOIN partner_name_match pnm ON pnm.raw_record_id = sr.raw_record_id
)
"""


def insert_candidate_filter() -> str:
    return "quantity > 0"


def audit_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)},
apparent_duplicate AS (
    SELECT
        movement_date,
        source_product_name,
        COALESCE(source_customer_name, '') AS source_customer_name,
        COALESCE(source_do_number, '') AS source_do_number,
        COALESCE(source_invoice_number, '') AS source_invoice_number,
        quantity,
        COUNT(*) AS row_count
    FROM resolved_rows
    WHERE {insert_candidate_filter()}
    GROUP BY
        movement_date,
        source_product_name,
        COALESCE(source_customer_name, ''),
        COALESCE(source_do_number, ''),
        COALESCE(source_invoice_number, ''),
        quantity
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Stock-out source rows from legacy fact_stock_out.' AS notes
FROM resolved_rows
UNION ALL
SELECT 'insert_candidate_rows', COUNT(*)::bigint, 'Rows with quantity > 0 that represent physical stock-out movement.'
FROM resolved_rows
WHERE {insert_candidate_filter()}
UNION ALL
SELECT 'skipped_missing_quantity_rows', COUNT(*)::bigint, 'Rows with blank quantity; skipped because they are not usable movement rows.'
FROM resolved_rows
WHERE quantity IS NULL
  AND source_quantity_raw IS NULL
UNION ALL
SELECT 'invalid_quantity_rows', COUNT(*)::bigint, 'Rows whose non-blank quantity could not be parsed.'
FROM resolved_rows
WHERE quantity IS NULL
  AND source_quantity_raw IS NOT NULL
UNION ALL
SELECT 'zero_or_negative_quantity_rows', COUNT(*)::bigint, 'Rows with quantity <= 0; skipped because they are not actual stock-out movement.'
FROM resolved_rows
WHERE quantity <= 0
UNION ALL
SELECT 'invalid_date_rows', COUNT(*)::bigint, 'Insert candidate rows whose ship date could not be parsed.'
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND movement_date IS NULL
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Insert candidate rows that do not resolve to dim_product/product_sku_alias.'
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND product_id IS NULL
UNION ALL
SELECT 'unmapped_b2b_partner_rows', COUNT(*)::bigint, 'Insert candidate rows with source b2b_partner_id/name that do not resolve to dim_b2b_partner.'
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND b2b_partner_id IS NULL
  AND source_b2b_partner_id IS NOT NULL
UNION ALL
SELECT 'unmatched_customer_name_rows', COUNT(*)::bigint, 'Insert candidate rows with free-text customer name but no dim_b2b_partner match; retained with b2b_partner_id NULL.'
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND b2b_partner_id IS NULL
  AND source_b2b_partner_id IS NULL
  AND source_customer_name_normalized IS NOT NULL
UNION ALL
SELECT 'blank_b2b_partner_rows', COUNT(*)::bigint, 'Insert candidate rows without source b2b partner id/name.'
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND source_b2b_partner_id IS NULL
  AND source_customer_name_normalized IS NULL
UNION ALL
SELECT 'blank_do_number_rows', COUNT(*)::bigint, 'Insert candidate rows without DO number.'
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND source_do_number IS NULL
UNION ALL
SELECT 'blank_invoice_number_rows', COUNT(*)::bigint, 'Insert candidate rows without invoice number.'
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND source_invoice_number IS NULL
UNION ALL
SELECT 'duplicate_source_row_extra_rows', GREATEST(COUNT(*) - COUNT(DISTINCT raw_record_id), 0)::bigint, 'Duplicate raw_record_id rows in temp source.'
FROM resolved_rows
UNION ALL
SELECT 'apparent_duplicate_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra rows by date/product/customer/document/quantity; retained as source lines.'
FROM apparent_duplicate
UNION ALL
SELECT 'existing_target_rows', COUNT(*)::bigint, 'Existing rows in fact_inventory_stock_movement for this source_system.'
FROM {target_schema}.fact_inventory_stock_movement
WHERE source_system = '{SOURCE_SYSTEM}';
"""


def insert_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
INSERT INTO {target_schema}.fact_inventory_stock_movement (
    source_system,
    movement_type,
    movement_subtype,
    movement_date,
    product_id,
    product_sku_alias_id,
    b2b_partner_id,
    source_stock_out_id,
    source_product_id,
    source_sku_code,
    source_product_name,
    product_match_method,
    source_b2b_partner_id,
    source_customer_name,
    b2b_partner_match_method,
    source_do_number,
    source_invoice_number,
    source_cargo_number,
    source_expedisi,
    quantity,
    source_quantity_ordered,
    source_quantity_shipped,
    unit,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    notes,
    updated_at
)
SELECT
    source_system,
    movement_type,
    movement_subtype,
    movement_date,
    product_id,
    product_sku_alias_id,
    b2b_partner_id,
    source_stock_out_id,
    source_product_id,
    source_sku_code,
    source_product_name,
    product_match_method,
    source_b2b_partner_id,
    source_customer_name,
    b2b_partner_match_method,
    source_do_number,
    source_invoice_number,
    source_cargo_number,
    source_expedisi,
    quantity,
    source_quantity_ordered,
    source_quantity_shipped,
    'PCS' AS unit,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    'Loaded by scripts/backfill/inventory_stock_movement_backfill.py; movement_subtype=' || COALESCE(movement_subtype, 'unknown') ||
        '; product_match_method=' || product_match_method ||
        '; b2b_partner_match_method=' || b2b_partner_match_method ||
        COALESCE('; source_notes=' || source_notes, '') AS notes,
    now()
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND movement_date IS NOT NULL
  AND product_id IS NOT NULL
  AND (
        b2b_partner_id IS NOT NULL
     OR source_b2b_partner_id IS NULL
  )
ON CONFLICT (source_system, raw_record_id) DO UPDATE SET
    movement_type = EXCLUDED.movement_type,
    movement_subtype = EXCLUDED.movement_subtype,
    movement_date = EXCLUDED.movement_date,
    product_id = EXCLUDED.product_id,
    product_sku_alias_id = EXCLUDED.product_sku_alias_id,
    b2b_partner_id = EXCLUDED.b2b_partner_id,
    source_stock_out_id = EXCLUDED.source_stock_out_id,
    source_product_id = EXCLUDED.source_product_id,
    source_sku_code = EXCLUDED.source_sku_code,
    source_product_name = EXCLUDED.source_product_name,
    product_match_method = EXCLUDED.product_match_method,
    source_b2b_partner_id = EXCLUDED.source_b2b_partner_id,
    source_customer_name = EXCLUDED.source_customer_name,
    b2b_partner_match_method = EXCLUDED.b2b_partner_match_method,
    source_do_number = EXCLUDED.source_do_number,
    source_invoice_number = EXCLUDED.source_invoice_number,
    source_cargo_number = EXCLUDED.source_cargo_number,
    source_expedisi = EXCLUDED.source_expedisi,
    quantity = EXCLUDED.quantity,
    source_quantity_ordered = EXCLUDED.source_quantity_ordered,
    source_quantity_shipped = EXCLUDED.source_quantity_shipped,
    unit = EXCLUDED.unit,
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
    source_product_name,
    source_product_label,
    COUNT(*) AS row_count,
    SUM(quantity) AS total_quantity,
    MIN(source_row_number) AS first_source_row_number
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND product_id IS NULL
GROUP BY source_sku_code, parsed_barcode, source_product_name, source_product_label
ORDER BY row_count DESC, source_product_name;
"""


def unmapped_partners_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    source_b2b_partner_id,
    source_customer_name,
    COUNT(*) AS row_count,
    SUM(quantity) AS total_quantity,
    MIN(source_row_number) AS first_source_row_number
FROM resolved_rows
WHERE {insert_candidate_filter()}
  AND b2b_partner_id IS NULL
  AND source_b2b_partner_id IS NOT NULL
GROUP BY source_b2b_partner_id, source_customer_name
ORDER BY row_count DESC, source_customer_name;
"""


def duplicate_grain_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    movement_date,
    source_product_name,
    source_customer_name,
    source_do_number,
    source_invoice_number,
    quantity,
    COUNT(*) AS row_count,
    STRING_AGG(raw_record_id, ' | ' ORDER BY raw_record_id) AS raw_record_ids
FROM resolved_rows
WHERE {insert_candidate_filter()}
GROUP BY
    movement_date,
    source_product_name,
    source_customer_name,
    source_do_number,
    source_invoice_number,
    quantity
HAVING COUNT(*) > 1
ORDER BY row_count DESC, movement_date, source_product_name;
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


def run_inventory_stock_movement_transform(
    conn: Connection,
    *,
    source_df: pd.DataFrame,
    target_schema: str = "public",
    execute: bool = False,
    allow_unmapped: bool = False,
    export_unmapped_products: str | Path | None = None,
    export_unmapped_partners: str | Path | None = None,
    export_duplicate_grain: str | Path | None = None,
) -> InventoryStockMovementTransformResult:
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

        if export_unmapped_partners:
            write_query_csv(conn, unmapped_partners_sql(target_schema), export_unmapped_partners)
            logger.info("Unmapped partner export: %s", Path(export_unmapped_partners).resolve())

        if export_duplicate_grain:
            write_query_csv(conn, duplicate_grain_sql(target_schema), export_duplicate_grain)
            logger.info("Duplicate grain export: %s", Path(export_duplicate_grain).resolve())

        blocking_metrics = (
            audit.value("invalid_quantity_rows"),
            audit.value("invalid_date_rows"),
            audit.value("unmapped_product_rows"),
            audit.value("unmapped_b2b_partner_rows"),
        )
        if any(value > 0 for value in blocking_metrics) and not allow_unmapped:
            raise RuntimeError(
                "Transform blocked: invalid date/quantity, unmapped product, or unmapped b2b partner rows "
                "detected. Fix mapping/source first, or rerun with --allow-unmapped for controlled testing."
            )

        if not execute:
            logger.info("Dry-run only. Add --execute to insert into target fact.")
            return InventoryStockMovementTransformResult(audit=audit, inventory_stock_movement_rows=0)

        logger.info("Execute inventory stock movement transform")
        insert_result = conn.execute(text(insert_sql(target_schema)))
        conn.execute(text(f"ANALYZE {target_schema}.fact_inventory_stock_movement"))
        logger.info("Inventory stock movement upsert finished: rows=%s", insert_result.rowcount)

        return InventoryStockMovementTransformResult(
            audit=audit,
            inventory_stock_movement_rows=insert_result.rowcount,
        )
    finally:
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.inventory_stock_movement_source"))
