"""Reusable production target transform."""

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
from scripts.transform.production_output import (
    SOURCE_RECORD_TYPE,
    SOURCE_SYSTEM as PRODUCTION_SOURCE_SYSTEM,
    extract_barcode,
    extract_product_label,
    extract_source_sku_token,
    read_production_csv,
)


logger = logging.getLogger(__name__)

LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"
SOURCE_SYSTEM = "legacy_wellfarm"


@dataclass(frozen=True)
class ProductionTargetTransformResult:
    audit: AuditResult
    production_target_rows: int


def read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(
        Path(path).expanduser().resolve(),
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )


def build_legacy_product_mapping(production_source_csv: str | Path) -> pd.DataFrame:
    production_df = read_production_csv(production_source_csv)
    rows = production_df[
        production_df["source_record_type"].eq(SOURCE_RECORD_TYPE)
        & production_df["source_sku_code"].ne("")
    ].copy()
    rows = rows[["source_sku_code", "parsed_barcode", "source_product_label"]].drop_duplicates()

    # The legacy target files carry old product_id values but not source SKU for
    # daily targets. This map is reconstructed from known legacy production IDs.
    legacy_map = {
        "1": ("8997224980831", "BERAS DIABET 1 KG"),
        "6": ("P5-8997224980831N", "BERAS DIABET 5 KG"),
        "7": ("P25-8997224980831", "BERAS DIABET 25 KG"),
        "8": ("8997224980824", "BERAS DIET 1 KG"),
        "11": ("P5-8997224980824N", "BERAS DIET 5 KG"),
        "12": ("", "BERAS DIET 25 KG"),
        "13": ("8997224980848", "BERAS OBIRICE 1 KG"),
        "16": ("8997224980855", "BERAS MERAH 1 KG"),
        "19": ("8997224980862", "BERAS COKLAT 1 KG"),
        "22": ("8997224980879", "BERAS HITAM 1 KG"),
        "25": ("8997224980886", "BERAS MENTHIK SUSU 1 KG"),
        "28": ("8997224980893", "BERAS MENTHIK WANGI 1 KG"),
        "31": ("8997224980909", "BERAS AMAZINC 1 KG"),
        "34": ("P5-8997224980909N", "BERAS AMAZINC 5 KG"),
        "35": ("", "BERAS AMAZINC 25 KG"),
        "36": ("8997224981104", "BERAS PORANG 1 KG"),
        "39": ("8997224981111", "BERAS PORANG 240 GR"),
        "40": ("8997224981135", "BERAS PORANG 40 GR"),
        "43": ("B9-8997224981135", "BERAS PORANG 40 GR 9 PCS"),
        "44": ("B10-8997224981135", "BERAS PORANG 40 GR 10 PCS"),
        "45": ("B11-8997224981135", "BERAS PORANG 40 GR 11 PCS"),
        "46": ("8997224981128", "KECAP SORGHUM 140 ML"),
        "47": ("8997224980978", "KECAP MANIS ORGANIK 140 ML"),
        "48": ("8997224980985", "KALDU SAPI PREMIUM 50 GR"),
        "49": ("8997224980992", "KALDU AYAM PREMIUM 50 GR"),
        "50": ("8997224981005", "KALDU JAMUR PREMIUM 50 GR"),
        "51": ("P5-8997224980848N", "BERAS OBIRICE 5 KG"),
        "53": ("P5-8997224980855N", "BERAS MERAH 5 KG"),
    }
    map_rows = []
    for source_product_id, (source_sku_code, fallback_product_label) in legacy_map.items():
        candidate = rows[rows["source_sku_code"].str.lower().eq(source_sku_code.lower())]
        if candidate.empty:
            parsed_barcode = extract_barcode(source_sku_code)
            source_product_label = fallback_product_label
        else:
            first = candidate.iloc[0]
            parsed_barcode = str(first["parsed_barcode"])
            source_product_label = str(first["source_product_label"]) or fallback_product_label
        map_rows.append(
            {
                "source_product_id": source_product_id,
                "source_sku_code": source_sku_code,
                "parsed_barcode": parsed_barcode,
                "source_product_label": source_product_label,
            }
        )
    return pd.DataFrame(map_rows)


def normalize_monthly_target(monthly_df: pd.DataFrame, source_path: str | Path) -> pd.DataFrame:
    source_file = Path(source_path).expanduser().resolve().name
    df = monthly_df.copy()
    for column in df.columns:
        df[column] = df[column].astype(str).str.strip()
    df["target_grain"] = "monthly"
    df["source_product_id"] = df["product_id"]
    df["source_product_name"] = df["product_name_raw"]
    df["target_year_norm"] = pd.to_numeric(df["target_year"], errors="coerce")
    df["target_month_norm"] = pd.to_numeric(df["target_month"], errors="coerce")
    df["target_day_norm"] = pd.to_numeric(df["target_day"], errors="coerce")
    df["target_quantity"] = pd.to_numeric(
        df["qty_target"].str.replace(",", "", regex=False), errors="coerce"
    )
    df["target_date"] = ""
    df["target_cycle_start"] = ""
    df["target_cycle_end"] = ""
    df["weekly_need_quantity"] = None
    df["generated_at"] = ""
    df["source_file"] = source_file
    df["source_sheet"] = "fact_production_target"
    df["source_row_number"] = df.index + 2
    df["raw_record_id"] = SOURCE_SYSTEM + ":" + source_file + ":monthly:" + df["source_row_number"].astype(str)
    return df


def normalize_daily_target(daily_df: pd.DataFrame, source_path: str | Path) -> pd.DataFrame:
    source_file = Path(source_path).expanduser().resolve().name
    df = daily_df.copy()
    for column in df.columns:
        df[column] = df[column].astype(str).str.strip()
    target_dates = pd.to_datetime(df["target_date"], errors="coerce")
    df["target_grain"] = "daily"
    df["source_product_id"] = df["product_id"]
    df["source_product_name"] = ""
    df["target_year_norm"] = target_dates.dt.year
    df["target_month_norm"] = target_dates.dt.month
    df["target_day_norm"] = target_dates.dt.day
    df["target_quantity"] = pd.to_numeric(
        df["target_qty_pcs"].str.replace(",", "", regex=False), errors="coerce"
    )
    df["target_date"] = target_dates.dt.strftime("%Y-%m-%d").fillna("")
    df["target_cycle_start"] = pd.to_datetime(df["target_cycle_start"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    df["target_cycle_end"] = pd.to_datetime(df["target_cycle_end"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    df["weekly_need_quantity"] = pd.to_numeric(
        df["weekly_need_pcs"].str.replace(",", "", regex=False), errors="coerce"
    )
    df["generated_at"] = df["generated_at"]
    df["source_file"] = source_file
    df["source_sheet"] = "fact_production_daily_target"
    df["source_row_number"] = df.index + 2
    df["raw_record_id"] = SOURCE_SYSTEM + ":" + source_file + ":daily:" + df["source_row_number"].astype(str)
    return df


def build_source_df(
    *,
    monthly_target_csv: str | Path,
    daily_target_csv: str | Path,
    production_source_csv: str | Path,
) -> pd.DataFrame:
    monthly = normalize_monthly_target(read_csv(monthly_target_csv), monthly_target_csv)
    daily = normalize_daily_target(read_csv(daily_target_csv), daily_target_csv)
    product_map = build_legacy_product_mapping(production_source_csv)

    combined = pd.concat([monthly, daily], ignore_index=True, sort=False)
    combined = combined.merge(product_map, how="left", on="source_product_id")
    combined["source_sku_code"] = combined["source_sku_code"].fillna("")
    combined["parsed_barcode"] = combined["parsed_barcode"].fillna("")
    combined["source_product_label"] = combined["source_product_label"].fillna("")

    return combined[
        [
            "target_grain",
            "target_date",
            "target_year_norm",
            "target_month_norm",
            "target_day_norm",
            "target_cycle_start",
            "target_cycle_end",
            "source_product_id",
            "source_sku_code",
            "parsed_barcode",
            "source_product_name",
            "source_product_label",
            "target_quantity",
            "weekly_need_quantity",
            "generated_at",
            "source_file",
            "source_sheet",
            "source_row_number",
            "raw_record_id",
        ]
    ]


def configure_transaction_guardrails(conn: Connection) -> None:
    lock_key = "production_target"
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
        "production_target_source",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    conn.execute(text('CREATE INDEX ON pg_temp.production_target_source ("target_grain")'))
    conn.execute(text('CREATE INDEX ON pg_temp.production_target_source ("source_product_id")'))
    conn.execute(text('CREATE INDEX ON pg_temp.production_target_source ("source_sku_code")'))
    conn.execute(text('CREATE INDEX ON pg_temp.production_target_source ("raw_record_id")'))
    conn.execute(text("ANALYZE pg_temp.production_target_source"))
    logger.info("Temporary production target source table created: rows=%s", len(df))


def resolution_cte(target_schema: str) -> str:
    return f"""
source_rows AS (
    SELECT
        NULLIF(TRIM(target_grain), '') AS target_grain,
        NULLIF(TRIM(target_date), '')::date AS target_date,
        target_year_norm::integer AS target_year,
        target_month_norm::integer AS target_month,
        target_day_norm::integer AS target_day,
        NULLIF(TRIM(target_cycle_start), '')::date AS target_cycle_start,
        NULLIF(TRIM(target_cycle_end), '')::date AS target_cycle_end,
        NULLIF(TRIM(source_product_id), '') AS source_product_id,
        NULLIF(TRIM(source_sku_code), '') AS source_sku_code,
        NULLIF(TRIM(parsed_barcode), '') AS parsed_barcode,
        NULLIF(TRIM(source_product_name), '') AS source_product_name,
        NULLIF(TRIM(source_product_label), '') AS source_product_label,
        target_quantity::numeric(18, 4) AS target_quantity,
        weekly_need_quantity::numeric(18, 4) AS weekly_need_quantity,
        NULLIF(TRIM(generated_at), '')::timestamptz AS generated_at,
        NULLIF(TRIM(source_file), '') AS source_file,
        NULLIF(TRIM(source_sheet), '') AS source_sheet,
        source_row_number::integer AS source_row_number,
        NULLIF(TRIM(raw_record_id), '') AS raw_record_id
    FROM pg_temp.production_target_source
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
        target_grain,
        target_date,
        target_year,
        target_month,
        target_day,
        source_product_id,
        COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY target_grain, target_date, target_year, target_month, target_day, source_product_id
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Monthly and daily target source rows.' AS notes
FROM resolved_rows
UNION ALL
SELECT 'monthly_target_rows', COUNT(*)::bigint, 'Rows from monthly production target source.'
FROM resolved_rows
WHERE target_grain = 'monthly'
UNION ALL
SELECT 'daily_target_rows', COUNT(*)::bigint, 'Rows from daily generated production target source.'
FROM resolved_rows
WHERE target_grain = 'daily'
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Target rows that do not resolve to dim_product/product_sku_alias.'
FROM resolved_rows
WHERE product_id IS NULL
UNION ALL
SELECT 'invalid_period_rows', COUNT(*)::bigint, 'Rows with invalid target year/month/date fields.'
FROM resolved_rows
WHERE target_year IS NULL
   OR target_month IS NULL
   OR (target_grain = 'daily' AND target_date IS NULL)
UNION ALL
SELECT 'invalid_quantity_rows', COUNT(*)::bigint, 'Rows whose target quantity could not be parsed.'
FROM resolved_rows
WHERE target_quantity IS NULL
UNION ALL
SELECT 'zero_quantity_rows', COUNT(*)::bigint, 'Rows with target quantity = 0; retained as explicit target values.'
FROM resolved_rows
WHERE target_quantity = 0
UNION ALL
SELECT 'duplicate_source_row_extra_rows', GREATEST(COUNT(*) - COUNT(DISTINCT raw_record_id), 0)::bigint, 'Duplicate raw_record_id rows in temp source.'
FROM resolved_rows
UNION ALL
SELECT 'apparent_duplicate_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra rows by target grain/period/product.'
FROM apparent_duplicate
UNION ALL
SELECT 'existing_target_rows', COUNT(*)::bigint, 'Existing rows in fact_production_target for this source_system.'
FROM {target_schema}.fact_production_target
WHERE source_system = '{SOURCE_SYSTEM}';
"""


def insert_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
INSERT INTO {target_schema}.fact_production_target (
    source_system,
    target_grain,
    target_date,
    target_year,
    target_month,
    target_day,
    target_cycle_start,
    target_cycle_end,
    product_id,
    product_sku_alias_id,
    source_product_id,
    source_sku_code,
    source_product_name,
    target_quantity,
    weekly_need_quantity,
    unit,
    generated_at,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    notes,
    updated_at
)
SELECT
    '{SOURCE_SYSTEM}' AS source_system,
    target_grain,
    target_date,
    target_year,
    target_month,
    target_day,
    target_cycle_start,
    target_cycle_end,
    product_id,
    product_sku_alias_id,
    source_product_id,
    source_sku_code,
    COALESCE(source_product_name, source_product_label, source_sku_code) AS source_product_name,
    target_quantity,
    weekly_need_quantity,
    'PCS' AS unit,
    generated_at,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    'Loaded by scripts/backfill/production_target_backfill.py; product_match_method=' || product_match_method AS notes,
    now() AS updated_at
FROM resolved_rows
WHERE product_id IS NOT NULL
  AND target_year IS NOT NULL
  AND target_month IS NOT NULL
  AND target_quantity IS NOT NULL
  AND (target_grain = 'monthly' OR target_date IS NOT NULL)
ON CONFLICT (source_system, raw_record_id) DO UPDATE SET
    target_grain = EXCLUDED.target_grain,
    target_date = EXCLUDED.target_date,
    target_year = EXCLUDED.target_year,
    target_month = EXCLUDED.target_month,
    target_day = EXCLUDED.target_day,
    target_cycle_start = EXCLUDED.target_cycle_start,
    target_cycle_end = EXCLUDED.target_cycle_end,
    product_id = EXCLUDED.product_id,
    product_sku_alias_id = EXCLUDED.product_sku_alias_id,
    source_product_id = EXCLUDED.source_product_id,
    source_sku_code = EXCLUDED.source_sku_code,
    source_product_name = EXCLUDED.source_product_name,
    target_quantity = EXCLUDED.target_quantity,
    weekly_need_quantity = EXCLUDED.weekly_need_quantity,
    unit = EXCLUDED.unit,
    generated_at = EXCLUDED.generated_at,
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
    target_grain,
    source_product_id,
    source_sku_code,
    parsed_barcode,
    COALESCE(source_product_name, source_product_label) AS source_product_name,
    COUNT(*) AS row_count,
    MIN(source_row_number) AS first_source_row_number,
    MAX(source_row_number) AS last_source_row_number
FROM resolved_rows
WHERE product_id IS NULL
GROUP BY target_grain, source_product_id, source_sku_code, parsed_barcode, COALESCE(source_product_name, source_product_label)
ORDER BY row_count DESC, target_grain, source_product_id;
"""


def duplicate_grain_sql(target_schema: str) -> str:
    return f"""
WITH {resolution_cte(target_schema)}
SELECT
    target_grain,
    target_date,
    target_year,
    target_month,
    target_day,
    source_product_id,
    source_sku_code,
    COUNT(*) AS row_count,
    COUNT(*) - 1 AS extra_rows,
    STRING_AGG(source_row_number::text, ', ' ORDER BY source_row_number) AS source_row_numbers
FROM resolved_rows
GROUP BY target_grain, target_date, target_year, target_month, target_day, source_product_id, source_sku_code
HAVING COUNT(*) > 1
ORDER BY extra_rows DESC, target_grain, target_year, target_month, source_product_id;
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


def run_production_target_transform(
    conn: Connection,
    *,
    source_df: pd.DataFrame,
    target_schema: str = "public",
    execute: bool = False,
    allow_unmapped: bool = False,
    export_unmapped_products: str | Path | None = None,
    export_duplicate_grain: str | Path | None = None,
) -> ProductionTargetTransformResult:
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
            audit.value("invalid_period_rows"),
            audit.value("invalid_quantity_rows"),
        )
        if any(value > 0 for value in blocking_metrics) and not allow_unmapped:
            raise RuntimeError(
                "Transform blocked: unmapped product, invalid period, or invalid quantity rows detected. "
                "Fix mapping/source first, or rerun with --allow-unmapped for controlled testing."
            )

        if not execute:
            logger.info("Dry-run only. Add --execute to insert into target fact.")
            return ProductionTargetTransformResult(audit=audit, production_target_rows=0)

        logger.info("Execute transform source_system=%s", SOURCE_SYSTEM)
        insert_result = conn.execute(text(insert_sql(target_schema)))
        conn.execute(text(f"ANALYZE {target_schema}.fact_production_target"))
        logger.info("Production target upsert finished: rows=%s", insert_result.rowcount)

        return ProductionTargetTransformResult(
            audit=audit,
            production_target_rows=insert_result.rowcount,
        )
    finally:
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.production_target_source"))
