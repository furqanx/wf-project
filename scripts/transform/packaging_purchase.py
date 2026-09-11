"""Reusable packaging purchase transform."""

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

LEGACY_SUPPLIER_LOOKUP_TOKEN = {
    "7": "putrama packaging",
    "8": "twinpack",
    "9": "flexy pack",
    "10": "indoceria",
    "11": "epac tanggerang",
    "12": "dikemas com",
    "13": "kardus custom",
    "14": "rasadi kardus sgm",
}


@dataclass(frozen=True)
class PackagingPurchaseTransformResult:
    audit: AuditResult
    packaging_purchase_rows: int


def normalize_text(value: object) -> str:
    text_value = str(value or "").strip().lower()
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(
        Path(path).expanduser().resolve(),
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )


def parse_yyyymmdd(value: object) -> str:
    text_value = str(value or "").strip()
    parsed = pd.to_datetime(text_value, format="%Y%m%d", errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def build_source_df(packaging_purchase_csv: str | Path) -> pd.DataFrame:
    source_path = Path(packaging_purchase_csv).expanduser().resolve()
    df = read_csv(source_path).copy()
    for column in df.columns:
        df[column] = df[column].astype(str).str.strip()

    df["source_system"] = SOURCE_SYSTEM
    df["source_purchase_id"] = df["purchase_id"]
    df["source_supplier_id"] = df["supplier_id"]
    df["supplier_lookup_token"] = df["source_supplier_id"].map(LEGACY_SUPPLIER_LOOKUP_TOKEN).fillna("")
    df["source_product_id"] = df["product_id"]
    df["source_packaging_name"] = df["packaging_name"]
    df["source_packaging_name_normalized"] = df["source_packaging_name"].map(normalize_text)
    df["invoice_date"] = df["invoice_date_id"].map(parse_yyyymmdd)
    df["received_date"] = df["received_date_id"].map(parse_yyyymmdd)
    df["dp_date"] = df["dp_date_id"].map(parse_yyyymmdd)
    df["paid_date"] = df["paid_date_id"].map(parse_yyyymmdd)
    df["quantity"] = pd.to_numeric(df["qty"].str.replace(",", "", regex=False), errors="coerce")
    df["unit_price_excl_vat_norm"] = pd.to_numeric(
        df["unit_price_excl_vat"].str.replace(",", "", regex=False),
        errors="coerce",
    )
    df["dp_amount_norm"] = pd.to_numeric(
        df["dp_amount"].str.replace(",", "", regex=False),
        errors="coerce",
    )
    df["subtotal_amount"] = df["quantity"] * df["unit_price_excl_vat_norm"]
    df["source_file"] = df["source_filename"].replace("", source_path.name)
    df["source_sheet"] = "fact_packaging_purchase"
    df["source_row_number"] = df.index + 2
    df["raw_record_id"] = (
        SOURCE_SYSTEM
        + ":"
        + df["source_file"].astype(str)
        + ":packaging_purchase:"
        + df["source_purchase_id"].astype(str)
    )

    return df[
        [
            "source_system",
            "source_purchase_id",
            "source_supplier_id",
            "supplier_lookup_token",
            "source_product_id",
            "source_packaging_name",
            "source_packaging_name_normalized",
            "ket_code",
            "po_number",
            "invoice_date",
            "received_date",
            "dp_date",
            "paid_date",
            "quantity",
            "unit_price_excl_vat_norm",
            "subtotal_amount",
            "dp_amount_norm",
            "source_file",
            "source_sheet",
            "source_row_number",
            "raw_record_id",
        ]
    ].rename(
        columns={
            "unit_price_excl_vat_norm": "unit_price_excl_vat",
            "dp_amount_norm": "dp_amount",
        }
    )


def configure_transaction_guardrails(conn: Connection) -> None:
    lock_key = "packaging_purchase"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def create_temp_table(conn: Connection, source_df: pd.DataFrame) -> None:
    source_df.to_sql(
        "packaging_purchase_source",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    conn.execute(text('CREATE INDEX ON pg_temp.packaging_purchase_source ("raw_record_id")'))
    conn.execute(text('CREATE INDEX ON pg_temp.packaging_purchase_source ("supplier_lookup_token")'))
    conn.execute(text('CREATE INDEX ON pg_temp.packaging_purchase_source ("source_packaging_name_normalized")'))
    conn.execute(text("ANALYZE pg_temp.packaging_purchase_source"))
    logger.info("Temporary packaging purchase source table created: rows=%s", len(source_df))


def resolution_cte(target_schema: str) -> str:
    return f"""
source_rows AS (
    SELECT
        NULLIF(TRIM(source_system), '') AS source_system,
        NULLIF(TRIM(source_purchase_id), '') AS source_purchase_id,
        NULLIF(TRIM(source_supplier_id), '') AS source_supplier_id,
        NULLIF(TRIM(supplier_lookup_token), '') AS supplier_lookup_token,
        NULLIF(TRIM(source_product_id), '') AS source_product_id,
        NULLIF(TRIM(source_packaging_name), '') AS source_packaging_name,
        NULLIF(TRIM(source_packaging_name_normalized), '') AS source_packaging_name_normalized,
        NULLIF(TRIM(ket_code), '') AS ket_code,
        NULLIF(TRIM(po_number), '') AS po_number,
        NULLIF(TRIM(invoice_date), '')::date AS invoice_date,
        NULLIF(TRIM(received_date), '')::date AS received_date,
        NULLIF(TRIM(dp_date), '')::date AS dp_date,
        NULLIF(TRIM(paid_date), '')::date AS paid_date,
        quantity::numeric(18, 4) AS quantity,
        unit_price_excl_vat::numeric(18, 2) AS unit_price_excl_vat,
        subtotal_amount::numeric(18, 2) AS subtotal_amount,
        dp_amount::numeric(18, 2) AS dp_amount,
        NULLIF(TRIM(source_file), '') AS source_file,
        NULLIF(TRIM(source_sheet), '') AS source_sheet,
        source_row_number::integer AS source_row_number,
        NULLIF(TRIM(raw_record_id), '') AS raw_record_id
    FROM pg_temp.packaging_purchase_source
),
supplier_match AS (
    SELECT DISTINCT ON (sr.raw_record_id)
        sr.raw_record_id,
        ds.supplier_id,
        'dim_supplier.lookup_token' AS supplier_match_method
    FROM source_rows sr
    JOIN {target_schema}.dim_supplier ds
      ON ds.is_active
     AND sr.supplier_lookup_token IS NOT NULL
     AND (
            ds.supplier_name_normalized = sr.supplier_lookup_token
         OR COALESCE(ds.company_name_normalized, '') = sr.supplier_lookup_token
         OR ds.supplier_name_normalized LIKE '%' || sr.supplier_lookup_token || '%'
         OR COALESCE(ds.company_name_normalized, '') LIKE '%' || sr.supplier_lookup_token || '%'
     )
    ORDER BY
        sr.raw_record_id,
        CASE
            WHEN ds.supplier_name_normalized = sr.supplier_lookup_token THEN 0
            WHEN COALESCE(ds.company_name_normalized, '') = sr.supplier_lookup_token THEN 1
            ELSE 2
        END,
        ds.supplier_id
),
item_match AS (
    SELECT DISTINCT ON (sr.raw_record_id)
        sr.raw_record_id,
        iisa.inventory_item_id,
        'inventory_item_source_alias.raw_name' AS inventory_item_match_method,
        iisa.match_confidence
    FROM source_rows sr
    JOIN {target_schema}.inventory_item_source_alias iisa
      ON iisa.is_active
     AND iisa.source_system = sr.source_system
     AND iisa.source_entity = 'fact_packaging_purchase'
     AND iisa.source_alias_type = 'raw_name'
     AND iisa.source_alias_normalized = sr.source_packaging_name_normalized
    ORDER BY
        sr.raw_record_id,
        CASE iisa.match_confidence
            WHEN 'high' THEN 0
            WHEN 'medium' THEN 1
            WHEN 'low' THEN 2
            ELSE 3
        END,
        iisa.inventory_item_source_alias_id
),
resolved_rows AS (
    SELECT
        sr.*,
        sm.supplier_id,
        COALESCE(sm.supplier_match_method, 'unmatched') AS supplier_match_method,
        im.inventory_item_id,
        COALESCE(im.inventory_item_match_method, 'unmatched') AS inventory_item_match_method,
        COALESCE(im.match_confidence, 'needs_review') AS inventory_item_match_confidence
    FROM source_rows sr
    LEFT JOIN supplier_match sm ON sm.raw_record_id = sr.raw_record_id
    LEFT JOIN item_match im ON im.raw_record_id = sr.raw_record_id
)
"""


def audit_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)},
duplicate_grain AS (
    SELECT source_system, source_purchase_id, COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY source_system, source_purchase_id
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Packaging purchase rows from source CSV.' AS notes
FROM resolved_rows
UNION ALL
SELECT 'purchase_rows', COUNT(*)::bigint, 'Distinct source purchase line grain before insert.'
FROM resolved_rows
UNION ALL
SELECT 'unmapped_supplier_rows', COUNT(*)::bigint, 'Rows whose source supplier id does not resolve to dim_supplier.'
FROM resolved_rows
WHERE supplier_id IS NULL
UNION ALL
SELECT 'unmapped_inventory_item_rows', COUNT(*)::bigint, 'Rows whose packaging name does not resolve to dim_inventory_item via alias.'
FROM resolved_rows
WHERE inventory_item_id IS NULL
UNION ALL
SELECT 'medium_confidence_item_rows', COUNT(*)::bigint, 'Rows resolved to packaging item with medium confidence.'
FROM resolved_rows
WHERE inventory_item_match_confidence = 'medium'
UNION ALL
SELECT 'invalid_invoice_date_rows', COUNT(*)::bigint, 'Rows whose invoice date could not be parsed.'
FROM resolved_rows
WHERE invoice_date IS NULL
UNION ALL
SELECT 'blank_received_date_rows', COUNT(*)::bigint, 'Rows whose received date is blank.'
FROM resolved_rows
WHERE received_date IS NULL
UNION ALL
SELECT 'invalid_quantity_rows', COUNT(*)::bigint, 'Rows whose quantity could not be parsed.'
FROM resolved_rows
WHERE quantity IS NULL
UNION ALL
SELECT 'zero_or_negative_quantity_rows', COUNT(*)::bigint, 'Rows with quantity <= 0.'
FROM resolved_rows
WHERE quantity <= 0
UNION ALL
SELECT 'invalid_unit_price_rows', COUNT(*)::bigint, 'Rows whose unit price could not be parsed.'
FROM resolved_rows
WHERE unit_price_excl_vat IS NULL
UNION ALL
SELECT 'duplicate_source_row_extra_rows', GREATEST(COUNT(*) - COUNT(DISTINCT raw_record_id), 0)::bigint, 'Duplicate raw_record_id rows in temp source.'
FROM resolved_rows
UNION ALL
SELECT 'apparent_duplicate_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra rows by source_system/source_purchase_id.'
FROM duplicate_grain
UNION ALL
SELECT 'existing_target_rows', COUNT(*)::bigint, 'Existing rows in fact_packaging_purchase for this source_system.'
FROM {target_schema}.fact_packaging_purchase
WHERE source_system = '{SOURCE_SYSTEM}';
"""


def insert_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
INSERT INTO {target_schema}.fact_packaging_purchase (
    source_system,
    supplier_id,
    inventory_item_id,
    source_purchase_id,
    source_supplier_id,
    supplier_match_method,
    source_product_id,
    source_packaging_name,
    inventory_item_match_method,
    ket_code,
    po_number,
    invoice_date,
    received_date,
    dp_date,
    paid_date,
    quantity,
    unit,
    unit_price_excl_vat,
    subtotal_amount,
    dp_amount,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    notes,
    updated_at
)
SELECT
    source_system,
    supplier_id,
    inventory_item_id,
    source_purchase_id,
    source_supplier_id,
    supplier_match_method,
    source_product_id,
    source_packaging_name,
    inventory_item_match_method,
    ket_code,
    po_number,
    invoice_date,
    received_date,
    dp_date,
    paid_date,
    quantity,
    'PCS' AS unit,
    unit_price_excl_vat,
    subtotal_amount,
    dp_amount,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    'Loaded by scripts/backfill/packaging_purchase_backfill.py; supplier_match_method=' || supplier_match_method ||
        '; inventory_item_match_method=' || inventory_item_match_method ||
        '; inventory_item_match_confidence=' || inventory_item_match_confidence AS notes,
    now()
FROM resolved_rows
WHERE supplier_id IS NOT NULL
  AND inventory_item_id IS NOT NULL
  AND invoice_date IS NOT NULL
  AND quantity > 0
  AND unit_price_excl_vat IS NOT NULL
ON CONFLICT (source_system, raw_record_id) DO UPDATE SET
    supplier_id = EXCLUDED.supplier_id,
    inventory_item_id = EXCLUDED.inventory_item_id,
    source_purchase_id = EXCLUDED.source_purchase_id,
    source_supplier_id = EXCLUDED.source_supplier_id,
    supplier_match_method = EXCLUDED.supplier_match_method,
    source_product_id = EXCLUDED.source_product_id,
    source_packaging_name = EXCLUDED.source_packaging_name,
    inventory_item_match_method = EXCLUDED.inventory_item_match_method,
    ket_code = EXCLUDED.ket_code,
    po_number = EXCLUDED.po_number,
    invoice_date = EXCLUDED.invoice_date,
    received_date = EXCLUDED.received_date,
    dp_date = EXCLUDED.dp_date,
    paid_date = EXCLUDED.paid_date,
    quantity = EXCLUDED.quantity,
    unit = EXCLUDED.unit,
    unit_price_excl_vat = EXCLUDED.unit_price_excl_vat,
    subtotal_amount = EXCLUDED.subtotal_amount,
    dp_amount = EXCLUDED.dp_amount,
    source_file = EXCLUDED.source_file,
    source_sheet = EXCLUDED.source_sheet,
    source_row_number = EXCLUDED.source_row_number,
    notes = EXCLUDED.notes,
    is_active = true,
    updated_at = now();
"""


def unmapped_suppliers_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    source_supplier_id,
    supplier_lookup_token,
    COUNT(*) AS row_count,
    SUM(quantity) AS total_quantity,
    MIN(source_row_number) AS first_source_row_number
FROM resolved_rows
WHERE supplier_id IS NULL
GROUP BY source_supplier_id, supplier_lookup_token
ORDER BY row_count DESC, source_supplier_id;
"""


def unmapped_items_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    source_packaging_name,
    source_packaging_name_normalized,
    COUNT(*) AS row_count,
    SUM(quantity) AS total_quantity,
    SUM(subtotal_amount) AS total_subtotal_amount,
    MIN(source_row_number) AS first_source_row_number
FROM resolved_rows
WHERE inventory_item_id IS NULL
GROUP BY source_packaging_name, source_packaging_name_normalized
ORDER BY row_count DESC, source_packaging_name;
"""


def duplicate_grain_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    source_system,
    source_purchase_id,
    COUNT(*) AS row_count,
    STRING_AGG(raw_record_id, ' | ' ORDER BY raw_record_id) AS raw_record_ids
FROM resolved_rows
GROUP BY source_system, source_purchase_id
HAVING COUNT(*) > 1
ORDER BY row_count DESC, source_purchase_id;
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


def run_packaging_purchase_transform(
    conn: Connection,
    *,
    source_df: pd.DataFrame,
    target_schema: str = "public",
    execute: bool = False,
    allow_unmapped: bool = False,
    export_unmapped_suppliers: str | Path | None = None,
    export_unmapped_items: str | Path | None = None,
    export_duplicate_grain: str | Path | None = None,
) -> PackagingPurchaseTransformResult:
    validate_identifier(target_schema, "target_schema")
    configure_transaction_guardrails(conn)
    create_temp_table(conn, source_df)

    try:
        logger.info("Run audit source_system=%s", SOURCE_SYSTEM)
        audit = run_audit_on_connection(conn, audit_sql(target_schema))
        print_audit(audit)

        if export_unmapped_suppliers:
            write_query_csv(conn, unmapped_suppliers_sql(target_schema), export_unmapped_suppliers)
            logger.info("Unmapped supplier export: %s", Path(export_unmapped_suppliers).resolve())

        if export_unmapped_items:
            write_query_csv(conn, unmapped_items_sql(target_schema), export_unmapped_items)
            logger.info("Unmapped item export: %s", Path(export_unmapped_items).resolve())

        if export_duplicate_grain:
            write_query_csv(conn, duplicate_grain_sql(target_schema), export_duplicate_grain)
            logger.info("Duplicate grain export: %s", Path(export_duplicate_grain).resolve())

        blocking_metrics = (
            audit.value("unmapped_supplier_rows"),
            audit.value("unmapped_inventory_item_rows"),
            audit.value("invalid_invoice_date_rows"),
            audit.value("invalid_quantity_rows"),
            audit.value("zero_or_negative_quantity_rows"),
            audit.value("invalid_unit_price_rows"),
        )
        if any(value > 0 for value in blocking_metrics) and not allow_unmapped:
            raise RuntimeError(
                "Transform blocked: unmapped supplier/item, invalid invoice date, "
                "invalid quantity, or invalid unit price rows detected. Fix mapping/source first, "
                "or rerun with --allow-unmapped for controlled testing."
            )

        if not execute:
            logger.info("Dry-run only. Add --execute to insert into target fact.")
            return PackagingPurchaseTransformResult(audit=audit, packaging_purchase_rows=0)

        logger.info("Execute packaging purchase transform")
        insert_result = conn.execute(text(insert_sql(target_schema)))
        conn.execute(text(f"ANALYZE {target_schema}.fact_packaging_purchase"))
        logger.info("Packaging purchase upsert finished: rows=%s", insert_result.rowcount)

        return PackagingPurchaseTransformResult(
            audit=audit,
            packaging_purchase_rows=insert_result.rowcount,
        )
    finally:
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.packaging_purchase_source"))
