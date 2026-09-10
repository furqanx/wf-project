"""Reusable raw material purchase transform."""

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
from scripts.transform.production_output import extract_barcode, extract_product_label, extract_source_sku_token


logger = logging.getLogger(__name__)

LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"
LEGACY_SOURCE_SYSTEM = "legacy_wellfarm"
LATEST_SOURCE_SYSTEM = "manual_spreadsheet"
LATEST_SOURCE_SHEET = "Bahan Baku"


@dataclass(frozen=True)
class RawMaterialPurchaseSource:
    header_df: pd.DataFrame
    item_df: pd.DataFrame


@dataclass(frozen=True)
class RawMaterialPurchaseTransformResult:
    audit: AuditResult
    purchase_rows: int
    purchase_item_rows: int


def read_csv(path: str | Path, *, header: int | None = 0) -> pd.DataFrame:
    return pd.read_csv(
        Path(path).expanduser().resolve(),
        header=header,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )


def normalize_text(value: object) -> str:
    text_value = str(value or "").strip().lower()
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def parse_money(value: object) -> float | None:
    text_value = str(value or "").strip()
    if text_value == "":
        return None
    text_value = (
        text_value.replace("Rp", "")
        .replace("rp", "")
        .replace(",", "")
        .replace(" ", "")
    )
    if text_value in {"", "-", "#REF!"}:
        return None
    try:
        return float(text_value)
    except ValueError:
        return None


def parse_bool(value: object) -> bool | None:
    text_value = str(value or "").strip().lower()
    if text_value in {"t", "true", "yes", "y", "1", "paid", "lunas"}:
        return True
    if text_value in {"f", "false", "no", "n", "0", "belum", "unpaid"}:
        return False
    return None


def parse_yyyymmdd(value: object) -> str:
    text_value = str(value or "").strip()
    parsed = pd.to_datetime(text_value, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text_value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def supplier_lookup_token(value: object) -> str:
    normalized = normalize_text(value)
    if "sidomulyo" in normalized:
        return "sidomulyo"
    if "appoli" in normalized:
        return "appoli"
    if "jakarta" in normalized:
        return "jakarta"
    return normalized


LEGACY_SUPPLIER_LOOKUP_TOKEN = {
    "1": "sidomulyo",
    "2": "appoli",
    "3": "magelang sekar langit",
    "4": "magelang mitayani",
    "17": "solo",
    "18": "jakarta",
}


def header_raw_record_id(source_system: str, source_file: str, source_key: object) -> str:
    return f"{source_system}:{source_file}:header:{str(source_key).strip()}"


def read_legacy_sources(
    *,
    legacy_header_csv: str | Path,
    legacy_item_csv: str | Path,
) -> RawMaterialPurchaseSource:
    header_source = Path(legacy_header_csv).expanduser().resolve()
    item_source = Path(legacy_item_csv).expanduser().resolve()

    header = read_csv(header_source).copy()
    item = read_csv(item_source).copy()
    for df in (header, item):
        for column in df.columns:
            df[column] = df[column].astype(str).str.strip()

    item = item[
        ~(
            item["qty_kg"].eq("")
            & item["unit_price"].eq("")
            & item["subtotal"].eq("")
        )
    ].copy()

    header["source_system"] = LEGACY_SOURCE_SYSTEM
    header["source_header_key"] = header["po_id"]
    header["source_supplier_id"] = header["supplier_id"]
    header["source_supplier_name"] = header["supplier_name_raw"]
    header["supplier_lookup_token"] = (
        header["source_supplier_id"].map(LEGACY_SUPPLIER_LOOKUP_TOKEN).fillna("")
    )
    header.loc[header["supplier_lookup_token"].eq(""), "supplier_lookup_token"] = header[
        "source_supplier_name"
    ].map(supplier_lookup_token)
    header["po_number_norm"] = header["po_number"]
    header["received_date"] = header["received_date_id"].map(parse_yyyymmdd)
    header["total_quantity_kg_norm"] = pd.to_numeric(header["total_qty_kg"], errors="coerce")
    header["subtotal_amount_norm"] = pd.to_numeric(header["subtotal_amount"], errors="coerce")
    header["shipping_amount_norm"] = pd.to_numeric(header["ongkir_amount"], errors="coerce")
    header["source_total_amount_norm"] = pd.to_numeric(header["total_amount"], errors="coerce")
    header["calculated_total_amount_norm"] = (
        header["subtotal_amount_norm"].fillna(0) + header["shipping_amount_norm"].fillna(0)
    )
    header["total_amount_norm"] = header["source_total_amount_norm"].combine_first(
        header["calculated_total_amount_norm"]
    )
    header["is_paid_norm"] = header["is_paid"].map(parse_bool)
    header["paid_amount_norm"] = pd.to_numeric(header["paid_amount"], errors="coerce")
    header["outstanding_amount_norm"] = pd.to_numeric(header["outstanding_amount"], errors="coerce")
    header["source_file_norm"] = header.get("source_filename", "").replace("", header_source.name)
    header["source_sheet"] = "fact_raw_material_purchase"
    header["source_row_number_norm"] = header.index + 2
    header["raw_record_id"] = [
        header_raw_record_id(LEGACY_SOURCE_SYSTEM, str(source_file), source_key)
        for source_file, source_key in zip(header["source_file_norm"], header["source_header_key"])
    ]

    item["source_system"] = LEGACY_SOURCE_SYSTEM
    item["source_item_id_norm"] = item["item_id"]
    item["source_header_raw_record_id"] = [
        header_raw_record_id(LEGACY_SOURCE_SYSTEM, str(source_file), source_key)
        for source_file, source_key in zip(item["source_filename"], item["po_id"])
    ]
    item["source_item_code"] = item["product_name_raw"].map(extract_source_sku_token)
    item["parsed_barcode"] = item["product_name_raw"].map(extract_barcode)
    item["source_item_name_norm"] = item["product_name_raw"].map(extract_product_label)
    item.loc[item["source_item_name_norm"].eq(""), "source_item_name_norm"] = item["product_name_raw"]
    item["quantity_kg_norm"] = pd.to_numeric(item["qty_kg"], errors="coerce")
    item["unit_price_norm"] = pd.to_numeric(item["unit_price"], errors="coerce")
    item["subtotal_amount_norm"] = pd.to_numeric(item["subtotal"], errors="coerce")
    item["source_file_norm"] = item["source_filename"].replace("", item_source.name)
    item["source_sheet"] = "fact_raw_material_purchase_item"
    item["source_row_number_norm"] = item.index + 2
    item["raw_record_id"] = (
        LEGACY_SOURCE_SYSTEM
        + ":"
        + item["source_file_norm"].astype(str)
        + ":item:"
        + item["source_item_id_norm"].astype(str)
    )

    return RawMaterialPurchaseSource(
        header_df=header[
            [
                "source_system",
                "source_header_key",
                "source_supplier_id",
                "source_supplier_name",
                "supplier_lookup_token",
                "po_number_norm",
                "internal_po_number",
                "received_date",
                "total_quantity_kg_norm",
                "subtotal_amount_norm",
                "shipping_amount_norm",
                "source_total_amount_norm",
                "calculated_total_amount_norm",
                "total_amount_norm",
                "is_paid_norm",
                "paid_amount_norm",
                "outstanding_amount_norm",
                "source_file_norm",
                "source_sheet",
                "source_row_number_norm",
                "raw_record_id",
                "notes",
            ]
        ].rename(
            columns={
                "po_number_norm": "po_number",
                "total_quantity_kg_norm": "total_quantity_kg",
                "subtotal_amount_norm": "subtotal_amount",
                "shipping_amount_norm": "shipping_amount",
                "source_total_amount_norm": "source_total_amount",
                "calculated_total_amount_norm": "calculated_total_amount",
                "total_amount_norm": "total_amount",
                "is_paid_norm": "is_paid",
                "paid_amount_norm": "paid_amount",
                "outstanding_amount_norm": "outstanding_amount",
                "source_file_norm": "source_file",
                "source_row_number_norm": "source_row_number",
            }
        ),
        item_df=item[
            [
                "source_system",
                "source_header_raw_record_id",
                "source_item_id_norm",
                "source_item_code",
                "parsed_barcode",
                "source_item_name_norm",
                "quantity_kg_norm",
                "unit_price_norm",
                "subtotal_amount_norm",
                "source_file_norm",
                "source_sheet",
                "source_row_number_norm",
                "raw_record_id",
            ]
        ].rename(
            columns={
                "source_item_id_norm": "source_item_id",
                "source_item_name_norm": "source_item_name",
                "quantity_kg_norm": "quantity_kg",
                "unit_price_norm": "unit_price",
                "subtotal_amount_norm": "subtotal_amount",
                "source_file_norm": "source_file",
                "source_row_number_norm": "source_row_number",
            }
        ),
    )


def read_latest_source(
    *,
    latest_source_csv: str | Path,
    latest_cutoff_date: str = "2026-04-25",
) -> RawMaterialPurchaseSource:
    source_path = Path(latest_source_csv).expanduser().resolve()
    raw = read_csv(source_path, header=None)

    left = raw.iloc[:, :14].copy()
    left.columns = [
        "blank",
        "source_supplier_name",
        "po_number",
        "received_date_raw",
        "source_item_raw",
        "quantity_raw",
        "unit_price_raw",
        "subtotal_raw",
        "source_total_raw",
        "total_quantity_kg_raw",
        "is_paid_raw",
        "paid_amount_raw",
        "outstanding_amount_raw",
        "payment_notes",
    ]
    left["source_row_number"] = left.index + 1
    left = left[left["source_row_number"] > 2].copy()

    for column in left.columns:
        if column != "source_row_number":
            left[column] = left[column].astype(str).str.strip()

    left = left[
        (left["source_supplier_name"] != "")
        & (left["po_number"] != "")
        & (left["received_date_raw"] != "")
        & (left["source_item_raw"] != "")
    ].copy()

    parsed_dates = pd.to_datetime(left["received_date_raw"], format="%d-%b-%Y", errors="coerce")
    left["received_date"] = parsed_dates.dt.strftime("%Y-%m-%d").fillna("")
    cutoff = pd.to_datetime(latest_cutoff_date).date()
    left = left[pd.to_datetime(left["received_date"], errors="coerce").dt.date >= cutoff].copy()

    left["source_system"] = LATEST_SOURCE_SYSTEM
    left["source_supplier_id"] = ""
    left["supplier_lookup_token"] = left["source_supplier_name"].map(supplier_lookup_token)
    left["quantity"] = left["quantity_raw"].map(parse_money)
    left["unit_price"] = left["unit_price_raw"].map(parse_money)
    left["subtotal_amount"] = left["subtotal_raw"].map(parse_money)
    left["source_total_amount"] = left["source_total_raw"].map(parse_money)
    left["total_quantity_kg"] = left["total_quantity_kg_raw"].map(parse_money)
    left["is_paid"] = left["is_paid_raw"].map(parse_bool)
    left["paid_amount"] = left["paid_amount_raw"].map(parse_money)
    left["outstanding_amount"] = left["outstanding_amount_raw"].map(parse_money)
    left["source_file"] = source_path.name
    left["source_sheet"] = LATEST_SOURCE_SHEET
    left["source_header_key"] = (
        left["source_supplier_name"].map(normalize_text)
        + ":"
        + left["po_number"].map(normalize_text)
        + ":"
        + left["received_date"].astype(str)
    )
    left["source_header_raw_record_id"] = [
        header_raw_record_id(LATEST_SOURCE_SYSTEM, source_path.name, source_key)
        for source_key in left["source_header_key"]
    ]
    left["is_shipping_line"] = left["source_item_raw"].map(normalize_text).eq("ongkir")

    header_rows = []
    for source_header_key, group in left.groupby("source_header_key", sort=False):
        material = group[~group["is_shipping_line"]]
        shipping = group[group["is_shipping_line"]]
        source_total_values = group["source_total_amount"].dropna()
        nonzero_source_total = source_total_values[source_total_values != 0]
        source_total = nonzero_source_total.iloc[-1] if not nonzero_source_total.empty else None
        subtotal = material["subtotal_amount"].fillna(0).sum()
        shipping_amount = shipping["subtotal_amount"].fillna(0).sum()
        calculated_total = subtotal + shipping_amount
        total_quantity_values = group["total_quantity_kg"].dropna()
        nonzero_total_quantity = total_quantity_values[total_quantity_values != 0]
        total_quantity = (
            nonzero_total_quantity.iloc[-1]
            if not nonzero_total_quantity.empty
            else material["quantity"].fillna(0).sum()
        )
        first = group.iloc[0]
        paid_values = group["paid_amount"].dropna()
        outstanding_values = group["outstanding_amount"].dropna()
        payment_notes = [
            value for value in group["payment_notes"].astype(str).str.strip().tolist() if value
        ]
        header_rows.append(
            {
                "source_system": LATEST_SOURCE_SYSTEM,
                "source_header_key": source_header_key,
                "source_supplier_id": "",
                "source_supplier_name": first["source_supplier_name"],
                "supplier_lookup_token": first["supplier_lookup_token"],
                "po_number": first["po_number"],
                "internal_po_number": "",
                "received_date": first["received_date"],
                "total_quantity_kg": total_quantity,
                "subtotal_amount": subtotal,
                "shipping_amount": shipping_amount,
                "source_total_amount": source_total,
                "calculated_total_amount": calculated_total,
                "total_amount": source_total if source_total is not None else calculated_total,
                "is_paid": bool(group["is_paid"].fillna(False).any()),
                "paid_amount": paid_values.iloc[-1] if not paid_values.empty else None,
                "outstanding_amount": outstanding_values.iloc[-1] if not outstanding_values.empty else None,
                "source_file": source_path.name,
                "source_sheet": LATEST_SOURCE_SHEET,
                "source_row_number": int(group["source_row_number"].min()),
                "raw_record_id": header_raw_record_id(LATEST_SOURCE_SYSTEM, source_path.name, source_header_key),
                "notes": "; ".join(payment_notes),
            }
        )

    item = left[~left["is_shipping_line"]].copy()
    item["source_item_id"] = item["source_row_number"].astype(str)
    item["source_item_code"] = item["source_item_raw"].map(extract_source_sku_token)
    item["parsed_barcode"] = item["source_item_raw"].map(extract_barcode)
    item["source_item_name"] = item["source_item_raw"].map(extract_product_label)
    item.loc[item["source_item_name"].eq(""), "source_item_name"] = item["source_item_raw"]
    item["raw_record_id"] = (
        LATEST_SOURCE_SYSTEM
        + ":"
        + item["source_file"].astype(str)
        + ":item:"
        + item["source_row_number"].astype(str)
    )

    return RawMaterialPurchaseSource(
        header_df=pd.DataFrame(header_rows),
        item_df=item[
            [
                "source_system",
                "source_header_raw_record_id",
                "source_item_id",
                "source_item_code",
                "parsed_barcode",
                "source_item_name",
                "quantity",
                "unit_price",
                "subtotal_amount",
                "source_file",
                "source_sheet",
                "source_row_number",
                "raw_record_id",
            ]
        ].rename(columns={"quantity": "quantity_kg"}),
    )


def build_source_tables(
    *,
    legacy_header_csv: str | Path | None = None,
    legacy_item_csv: str | Path | None = None,
    latest_source_csv: str | Path | None = None,
    latest_cutoff_date: str = "2026-04-25",
) -> RawMaterialPurchaseSource:
    sources: list[RawMaterialPurchaseSource] = []
    if legacy_header_csv and legacy_item_csv:
        sources.append(
            read_legacy_sources(
                legacy_header_csv=legacy_header_csv,
                legacy_item_csv=legacy_item_csv,
            )
        )
    if latest_source_csv:
        sources.append(
            read_latest_source(
                latest_source_csv=latest_source_csv,
                latest_cutoff_date=latest_cutoff_date,
            )
        )
    if not sources:
        raise ValueError("At least one legacy source pair or latest source CSV must be provided.")

    return RawMaterialPurchaseSource(
        header_df=pd.concat([source.header_df for source in sources], ignore_index=True, sort=False),
        item_df=pd.concat([source.item_df for source in sources], ignore_index=True, sort=False),
    )


def configure_transaction_guardrails(conn: Connection) -> None:
    lock_key = "raw_material_purchase"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def create_temp_tables(conn: Connection, source: RawMaterialPurchaseSource) -> None:
    source.header_df.to_sql(
        "raw_material_purchase_header_source",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    source.item_df.to_sql(
        "raw_material_purchase_item_source",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    conn.execute(text('CREATE INDEX ON pg_temp.raw_material_purchase_header_source ("raw_record_id")'))
    conn.execute(text('CREATE INDEX ON pg_temp.raw_material_purchase_header_source ("supplier_lookup_token")'))
    conn.execute(text('CREATE INDEX ON pg_temp.raw_material_purchase_item_source ("source_header_raw_record_id")'))
    conn.execute(text('CREATE INDEX ON pg_temp.raw_material_purchase_item_source ("raw_record_id")'))
    conn.execute(text('CREATE INDEX ON pg_temp.raw_material_purchase_item_source ("parsed_barcode")'))
    conn.execute(text("ANALYZE pg_temp.raw_material_purchase_header_source"))
    conn.execute(text("ANALYZE pg_temp.raw_material_purchase_item_source"))
    logger.info(
        "Temporary raw material source tables created: header_rows=%s item_rows=%s",
        len(source.header_df),
        len(source.item_df),
    )


def resolution_cte(target_schema: str) -> str:
    return f"""
header_rows AS (
    SELECT
        NULLIF(TRIM(source_system), '') AS source_system,
        NULLIF(TRIM(source_header_key), '') AS source_header_key,
        NULLIF(TRIM(source_supplier_id), '') AS source_supplier_id,
        NULLIF(TRIM(source_supplier_name), '') AS source_supplier_name,
        NULLIF(TRIM(supplier_lookup_token), '') AS supplier_lookup_token,
        NULLIF(TRIM(po_number), '') AS po_number,
        NULLIF(TRIM(internal_po_number), '') AS internal_po_number,
        NULLIF(TRIM(received_date), '')::date AS received_date,
        total_quantity_kg::numeric(18, 4) AS total_quantity_kg,
        subtotal_amount::numeric(18, 2) AS subtotal_amount,
        shipping_amount::numeric(18, 2) AS shipping_amount,
        source_total_amount::numeric(18, 2) AS source_total_amount,
        calculated_total_amount::numeric(18, 2) AS calculated_total_amount,
        total_amount::numeric(18, 2) AS total_amount,
        is_paid::boolean AS is_paid,
        paid_amount::numeric(18, 2) AS paid_amount,
        outstanding_amount::numeric(18, 2) AS outstanding_amount,
        NULLIF(TRIM(source_file), '') AS source_file,
        NULLIF(TRIM(source_sheet), '') AS source_sheet,
        source_row_number::integer AS source_row_number,
        NULLIF(TRIM(raw_record_id), '') AS raw_record_id,
        NULLIF(TRIM(notes), '') AS notes
    FROM pg_temp.raw_material_purchase_header_source
),
supplier_match AS (
    SELECT DISTINCT ON (hr.raw_record_id)
        hr.raw_record_id,
        ds.supplier_id,
        CASE
            WHEN ds.source_supplier_id = hr.source_supplier_id
                 AND ds.source_system = hr.source_system
                 AND hr.source_supplier_id IS NOT NULL THEN 'dim_supplier.source_supplier_id'
            WHEN ds.supplier_name_normalized = LOWER(REGEXP_REPLACE(hr.source_supplier_name, '[^a-zA-Z0-9]+', ' ', 'g')) THEN 'dim_supplier.name_exact'
            ELSE 'dim_supplier.lookup_token'
        END AS supplier_match_method
    FROM header_rows hr
    JOIN {target_schema}.dim_supplier ds
      ON ds.is_active
     AND (
            (
                hr.source_supplier_id IS NOT NULL
                AND ds.source_system = hr.source_system
                AND ds.source_supplier_id = hr.source_supplier_id
            )
         OR ds.supplier_name_normalized = LOWER(REGEXP_REPLACE(hr.source_supplier_name, '[^a-zA-Z0-9]+', ' ', 'g'))
         OR (
                hr.supplier_lookup_token IS NOT NULL
                AND (
                    ds.supplier_name_normalized LIKE '%' || hr.supplier_lookup_token || '%'
                    OR COALESCE(ds.company_name_normalized, '') LIKE '%' || hr.supplier_lookup_token || '%'
                )
            )
     )
    ORDER BY
        hr.raw_record_id,
        CASE
            WHEN ds.source_supplier_id = hr.source_supplier_id
                 AND ds.source_system = hr.source_system
                 AND hr.source_supplier_id IS NOT NULL THEN 0
            WHEN ds.supplier_name_normalized = LOWER(REGEXP_REPLACE(hr.source_supplier_name, '[^a-zA-Z0-9]+', ' ', 'g')) THEN 1
            ELSE 2
        END,
        ds.supplier_id
),
resolved_headers AS (
    SELECT
        hr.*,
        sm.supplier_id,
        COALESCE(sm.supplier_match_method, 'unmatched') AS supplier_match_method
    FROM header_rows hr
    LEFT JOIN supplier_match sm ON sm.raw_record_id = hr.raw_record_id
),
item_rows AS (
    SELECT
        NULLIF(TRIM(source_system), '') AS source_system,
        NULLIF(TRIM(source_header_raw_record_id), '') AS source_header_raw_record_id,
        NULLIF(TRIM(source_item_id), '') AS source_item_id,
        NULLIF(TRIM(source_item_code), '') AS source_item_code,
        NULLIF(TRIM(parsed_barcode), '') AS parsed_barcode,
        NULLIF(TRIM(source_item_name), '') AS source_item_name,
        quantity_kg::numeric(18, 4) AS quantity_kg,
        unit_price::numeric(18, 2) AS unit_price,
        subtotal_amount::numeric(18, 2) AS subtotal_amount,
        NULLIF(TRIM(source_file), '') AS source_file,
        NULLIF(TRIM(source_sheet), '') AS source_sheet,
        source_row_number::integer AS source_row_number,
        NULLIF(TRIM(raw_record_id), '') AS raw_record_id
    FROM pg_temp.raw_material_purchase_item_source
),
item_match AS (
    SELECT DISTINCT ON (ir.raw_record_id)
        ir.raw_record_id,
        di.inventory_item_id,
        CASE
            WHEN di.item_code = 'RM-' || ir.parsed_barcode THEN 'dim_inventory_item.item_code_from_barcode'
            ELSE 'dim_inventory_item.name'
        END AS inventory_item_match_method
    FROM item_rows ir
    JOIN {target_schema}.dim_inventory_item di
      ON di.is_active
     AND di.item_type = 'raw_material'
     AND (
            (
                ir.parsed_barcode IS NOT NULL
                AND di.item_code = 'RM-' || ir.parsed_barcode
            )
         OR LOWER(REGEXP_REPLACE(di.item_name, '[^a-zA-Z0-9]+', ' ', 'g')) =
            LOWER(REGEXP_REPLACE(ir.source_item_name, '[^a-zA-Z0-9]+', ' ', 'g'))
     )
    ORDER BY
        ir.raw_record_id,
        CASE WHEN di.item_code = 'RM-' || ir.parsed_barcode THEN 0 ELSE 1 END,
        di.inventory_item_id
),
resolved_items AS (
    SELECT
        ir.*,
        im.inventory_item_id,
        COALESCE(im.inventory_item_match_method, 'unmatched') AS inventory_item_match_method,
        rh.raw_record_id AS resolved_header_raw_record_id
    FROM item_rows ir
    LEFT JOIN item_match im ON im.raw_record_id = ir.raw_record_id
    LEFT JOIN resolved_headers rh
      ON rh.source_system = ir.source_system
     AND rh.raw_record_id = ir.source_header_raw_record_id
)
"""


def audit_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)},
duplicate_header_grain AS (
    SELECT source_system, source_supplier_name, po_number, received_date, COUNT(*) AS row_count
    FROM resolved_headers
    GROUP BY source_system, source_supplier_name, po_number, received_date
    HAVING COUNT(*) > 1
),
duplicate_item_grain AS (
    SELECT source_system, source_header_raw_record_id, source_item_code, source_item_name, quantity_kg, subtotal_amount, COUNT(*) AS row_count
    FROM resolved_items
    GROUP BY source_system, source_header_raw_record_id, source_item_code, source_item_name, quantity_kg, subtotal_amount
    HAVING COUNT(*) > 1
)
SELECT 'source_header_rows' AS metric, COUNT(*)::bigint AS value, 'Raw material purchase header rows from source files.' AS notes
FROM resolved_headers
UNION ALL
SELECT 'source_item_rows', COUNT(*)::bigint, 'Raw material purchase item rows from source files.'
FROM resolved_items
UNION ALL
SELECT 'legacy_header_rows', COUNT(*)::bigint, 'Header rows sourced from legacy wellfarm export.'
FROM resolved_headers
WHERE source_system = '{LEGACY_SOURCE_SYSTEM}'
UNION ALL
SELECT 'latest_header_rows', COUNT(*)::bigint, 'Header rows sourced from latest Hasan spreadsheet cutoff.'
FROM resolved_headers
WHERE source_system = '{LATEST_SOURCE_SYSTEM}'
UNION ALL
SELECT 'unmapped_supplier_rows', COUNT(*)::bigint, 'Header rows whose supplier does not resolve to dim_supplier.'
FROM resolved_headers
WHERE supplier_id IS NULL
UNION ALL
SELECT 'unmapped_inventory_item_rows', COUNT(*)::bigint, 'Item rows whose material does not resolve to dim_inventory_item.'
FROM resolved_items
WHERE inventory_item_id IS NULL
UNION ALL
SELECT 'item_without_header_rows', COUNT(*)::bigint, 'Item rows whose source header does not exist in source header rows.'
FROM resolved_items
WHERE resolved_header_raw_record_id IS NULL
UNION ALL
SELECT 'invalid_header_date_rows', COUNT(*)::bigint, 'Header rows whose received date could not be parsed.'
FROM resolved_headers
WHERE received_date IS NULL
UNION ALL
SELECT 'invalid_item_quantity_rows', COUNT(*)::bigint, 'Item rows whose quantity could not be parsed.'
FROM resolved_items
WHERE quantity_kg IS NULL
UNION ALL
SELECT 'zero_or_negative_item_quantity_rows', COUNT(*)::bigint, 'Item rows with quantity <= 0; skipped during insert.'
FROM resolved_items
WHERE quantity_kg <= 0
UNION ALL
SELECT 'duplicate_header_source_row_extra_rows', GREATEST(COUNT(*) - COUNT(DISTINCT raw_record_id), 0)::bigint, 'Duplicate header raw_record_id rows in temp source.'
FROM resolved_headers
UNION ALL
SELECT 'duplicate_item_source_row_extra_rows', GREATEST(COUNT(*) - COUNT(DISTINCT raw_record_id), 0)::bigint, 'Duplicate item raw_record_id rows in temp source.'
FROM resolved_items
UNION ALL
SELECT 'apparent_duplicate_header_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra header rows by source/supplier/PO/date.'
FROM duplicate_header_grain
UNION ALL
SELECT 'apparent_duplicate_item_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra item rows by source/header/material/quantity/amount; retained as source lines.'
FROM duplicate_item_grain
UNION ALL
SELECT 'existing_header_rows', COUNT(*)::bigint, 'Existing rows in fact_raw_material_purchase for these source systems.'
FROM {target_schema}.fact_raw_material_purchase
WHERE source_system IN ('{LEGACY_SOURCE_SYSTEM}', '{LATEST_SOURCE_SYSTEM}')
UNION ALL
SELECT 'existing_item_rows', COUNT(*)::bigint, 'Existing rows in fact_raw_material_purchase_item for these source systems.'
FROM {target_schema}.fact_raw_material_purchase_item
WHERE source_system IN ('{LEGACY_SOURCE_SYSTEM}', '{LATEST_SOURCE_SYSTEM}');
"""


def insert_headers_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
INSERT INTO {target_schema}.fact_raw_material_purchase (
    source_system,
    supplier_id,
    source_supplier_id,
    source_supplier_name,
    supplier_match_method,
    po_number,
    internal_po_number,
    received_date,
    total_quantity_kg,
    subtotal_amount,
    shipping_amount,
    source_total_amount,
    calculated_total_amount,
    total_amount,
    is_paid,
    paid_amount,
    outstanding_amount,
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
    source_supplier_id,
    source_supplier_name,
    supplier_match_method,
    po_number,
    internal_po_number,
    received_date,
    total_quantity_kg,
    subtotal_amount,
    shipping_amount,
    source_total_amount,
    calculated_total_amount,
    total_amount,
    is_paid,
    paid_amount,
    outstanding_amount,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    'Loaded by scripts/backfill/raw_material_purchase_backfill.py; supplier_match_method=' || supplier_match_method ||
        COALESCE('; source_notes=' || notes, '') AS notes,
    now()
FROM resolved_headers
WHERE supplier_id IS NOT NULL
  AND received_date IS NOT NULL
ON CONFLICT (source_system, raw_record_id) DO UPDATE SET
    supplier_id = EXCLUDED.supplier_id,
    source_supplier_id = EXCLUDED.source_supplier_id,
    source_supplier_name = EXCLUDED.source_supplier_name,
    supplier_match_method = EXCLUDED.supplier_match_method,
    po_number = EXCLUDED.po_number,
    internal_po_number = EXCLUDED.internal_po_number,
    received_date = EXCLUDED.received_date,
    total_quantity_kg = EXCLUDED.total_quantity_kg,
    subtotal_amount = EXCLUDED.subtotal_amount,
    shipping_amount = EXCLUDED.shipping_amount,
    source_total_amount = EXCLUDED.source_total_amount,
    calculated_total_amount = EXCLUDED.calculated_total_amount,
    total_amount = EXCLUDED.total_amount,
    is_paid = EXCLUDED.is_paid,
    paid_amount = EXCLUDED.paid_amount,
    outstanding_amount = EXCLUDED.outstanding_amount,
    source_file = EXCLUDED.source_file,
    source_sheet = EXCLUDED.source_sheet,
    source_row_number = EXCLUDED.source_row_number,
    notes = EXCLUDED.notes,
    is_active = true,
    updated_at = now();
"""


def insert_items_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
INSERT INTO {target_schema}.fact_raw_material_purchase_item (
    raw_material_purchase_id,
    source_system,
    inventory_item_id,
    source_item_id,
    source_item_code,
    parsed_barcode,
    source_item_name,
    inventory_item_match_method,
    quantity_kg,
    unit_price,
    subtotal_amount,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    notes,
    updated_at
)
SELECT
    frmp.raw_material_purchase_id,
    ri.source_system,
    ri.inventory_item_id,
    ri.source_item_id,
    ri.source_item_code,
    ri.parsed_barcode,
    ri.source_item_name,
    ri.inventory_item_match_method,
    ri.quantity_kg,
    ri.unit_price,
    ri.subtotal_amount,
    ri.source_file,
    ri.source_sheet,
    ri.source_row_number,
    ri.raw_record_id,
    'Loaded by scripts/backfill/raw_material_purchase_backfill.py; inventory_item_match_method=' || ri.inventory_item_match_method AS notes,
    now()
FROM resolved_items ri
JOIN {target_schema}.fact_raw_material_purchase frmp
  ON frmp.source_system = ri.source_system
 AND frmp.raw_record_id = ri.source_header_raw_record_id
WHERE ri.inventory_item_id IS NOT NULL
  AND ri.quantity_kg > 0
ON CONFLICT (source_system, raw_record_id) DO UPDATE SET
    raw_material_purchase_id = EXCLUDED.raw_material_purchase_id,
    inventory_item_id = EXCLUDED.inventory_item_id,
    source_item_id = EXCLUDED.source_item_id,
    source_item_code = EXCLUDED.source_item_code,
    parsed_barcode = EXCLUDED.parsed_barcode,
    source_item_name = EXCLUDED.source_item_name,
    inventory_item_match_method = EXCLUDED.inventory_item_match_method,
    quantity_kg = EXCLUDED.quantity_kg,
    unit_price = EXCLUDED.unit_price,
    subtotal_amount = EXCLUDED.subtotal_amount,
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
    source_system,
    source_supplier_id,
    source_supplier_name,
    supplier_lookup_token,
    COUNT(*) AS row_count,
    MIN(source_file) AS sample_source_file,
    MIN(source_row_number) AS first_source_row_number
FROM resolved_headers
WHERE supplier_id IS NULL
GROUP BY source_system, source_supplier_id, source_supplier_name, supplier_lookup_token
ORDER BY row_count DESC, source_system, source_supplier_name;
"""


def unmapped_items_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    source_system,
    source_item_code,
    parsed_barcode,
    source_item_name,
    COUNT(*) AS row_count,
    SUM(quantity_kg) AS total_quantity_kg,
    SUM(subtotal_amount) AS total_subtotal_amount,
    MIN(source_file) AS sample_source_file,
    MIN(source_row_number) AS first_source_row_number
FROM resolved_items
WHERE inventory_item_id IS NULL
GROUP BY source_system, source_item_code, parsed_barcode, source_item_name
ORDER BY row_count DESC, source_system, source_item_name;
"""


def duplicate_grain_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    source_system,
    source_supplier_name,
    po_number,
    received_date,
    COUNT(*) AS header_row_count,
    STRING_AGG(raw_record_id, ' | ' ORDER BY raw_record_id) AS raw_record_ids
FROM resolved_headers
GROUP BY source_system, source_supplier_name, po_number, received_date
HAVING COUNT(*) > 1
ORDER BY header_row_count DESC, source_system, received_date, po_number;
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


def run_raw_material_purchase_transform(
    conn: Connection,
    *,
    source: RawMaterialPurchaseSource,
    target_schema: str = "public",
    execute: bool = False,
    allow_unmapped: bool = False,
    export_unmapped_suppliers: str | Path | None = None,
    export_unmapped_items: str | Path | None = None,
    export_duplicate_grain: str | Path | None = None,
) -> RawMaterialPurchaseTransformResult:
    validate_identifier(target_schema, "target_schema")
    configure_transaction_guardrails(conn)
    create_temp_tables(conn, source)

    try:
        logger.info("Run audit source_system=raw_material_purchase")
        audit = run_audit_on_connection(conn, audit_sql(target_schema))
        print_audit(audit)

        if export_unmapped_suppliers:
            write_query_csv(conn, unmapped_suppliers_sql(target_schema), export_unmapped_suppliers)
            logger.info("Unmapped supplier export: %s", Path(export_unmapped_suppliers).resolve())

        if export_unmapped_items:
            write_query_csv(conn, unmapped_items_sql(target_schema), export_unmapped_items)
            logger.info("Unmapped inventory item export: %s", Path(export_unmapped_items).resolve())

        if export_duplicate_grain:
            write_query_csv(conn, duplicate_grain_sql(target_schema), export_duplicate_grain)
            logger.info("Duplicate grain export: %s", Path(export_duplicate_grain).resolve())

        blocking_metrics = (
            audit.value("unmapped_supplier_rows"),
            audit.value("unmapped_inventory_item_rows"),
            audit.value("item_without_header_rows"),
            audit.value("invalid_header_date_rows"),
            audit.value("invalid_item_quantity_rows"),
        )
        if any(value > 0 for value in blocking_metrics) and not allow_unmapped:
            raise RuntimeError(
                "Transform blocked: unmapped supplier/item, item without header, invalid date, "
                "or invalid quantity rows detected. Fix mapping/source first, or rerun with "
                "--allow-unmapped for controlled testing."
            )

        if not execute:
            logger.info("Dry-run only. Add --execute to insert into target facts.")
            return RawMaterialPurchaseTransformResult(
                audit=audit,
                purchase_rows=0,
                purchase_item_rows=0,
            )

        logger.info("Execute raw material purchase transform")
        header_result = conn.execute(text(insert_headers_sql(target_schema)))
        logger.info("Raw material purchase header upsert finished: rows=%s", header_result.rowcount)
        item_result = conn.execute(text(insert_items_sql(target_schema)))
        logger.info("Raw material purchase item upsert finished: rows=%s", item_result.rowcount)
        conn.execute(text(f"ANALYZE {target_schema}.fact_raw_material_purchase"))
        conn.execute(text(f"ANALYZE {target_schema}.fact_raw_material_purchase_item"))

        return RawMaterialPurchaseTransformResult(
            audit=audit,
            purchase_rows=header_result.rowcount,
            purchase_item_rows=item_result.rowcount,
        )
    finally:
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.raw_material_purchase_header_source"))
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.raw_material_purchase_item_source"))
