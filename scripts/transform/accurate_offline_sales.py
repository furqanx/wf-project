"""Transform Accurate sales receipt/invoice audit CSVs into phase-1 sales facts."""

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
class AccurateOfflineSalesTransformResult:
    audit: AuditResult
    order_rows: int
    item_rows: int


def read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(
        Path(path),
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )


def create_temp_tables(
    conn: Connection,
    *,
    receipt_df: pd.DataFrame,
    invoice_df: pd.DataFrame,
    item_df: pd.DataFrame,
) -> None:
    receipt_df.to_sql(
        "accurate_sales_receipt",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    invoice_df.to_sql(
        "accurate_sales_invoice",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    item_df.to_sql(
        "accurate_sales_invoice_item",
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )

    conn.execute(text("CREATE INDEX ON pg_temp.accurate_sales_receipt (receipt_id)"))
    conn.execute(text("CREATE INDEX ON pg_temp.accurate_sales_receipt (receipt_number)"))
    conn.execute(text("CREATE INDEX ON pg_temp.accurate_sales_invoice (invoice_id)"))
    conn.execute(text("CREATE INDEX ON pg_temp.accurate_sales_invoice (invoice_number)"))
    conn.execute(text("CREATE INDEX ON pg_temp.accurate_sales_invoice_item (invoice_id)"))
    conn.execute(text("CREATE INDEX ON pg_temp.accurate_sales_invoice_item (accurate_item_no)"))
    conn.execute(text("ANALYZE pg_temp.accurate_sales_receipt"))
    conn.execute(text("ANALYZE pg_temp.accurate_sales_invoice"))
    conn.execute(text("ANALYZE pg_temp.accurate_sales_invoice_item"))

    logger.info(
        "Temporary Accurate offline sales tables created: receipt_rows=%s invoice_rows=%s item_rows=%s",
        len(receipt_df),
        len(invoice_df),
        len(item_df),
    )


def configure_transaction_guardrails(conn: Connection) -> None:
    lock_key = "sales_phase_1:accurate_offline"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def run_accurate_offline_sales_transform(
    conn: Connection,
    *,
    receipt_df: pd.DataFrame,
    invoice_df: pd.DataFrame,
    item_df: pd.DataFrame,
    target_schema: str = "public",
    execute: bool = False,
    allow_unmapped: bool = False,
    export_unmapped_products: str | Path | None = None,
    export_duplicate_grain: str | Path | None = None,
) -> AccurateOfflineSalesTransformResult:
    ctx = TransformContext(staging_schema="pg_temp", target_schema=target_schema)
    configure_transaction_guardrails(conn)
    create_temp_tables(conn, receipt_df=receipt_df, invoice_df=invoice_df, item_df=item_df)

    try:
        logger.info("Run audit source_system=accurate sales_channel_type=offline")
        audit = run_audit_on_connection(conn, audit_sql(ctx))
        print_audit(audit)

        if export_unmapped_products:
            write_query_csv(conn, unmapped_products_sql(ctx), export_unmapped_products)
            logger.info("Unmapped product export: %s", Path(export_unmapped_products).resolve())

        if export_duplicate_grain:
            write_query_csv(conn, duplicate_grain_sql(ctx), export_duplicate_grain)
            logger.info("Duplicate grain export: %s", Path(export_duplicate_grain).resolve())

        blocking_metrics = (
            audit.value("invoice_without_receipt_rows"),
            audit.value("item_without_invoice_rows"),
            audit.value("unmapped_product_rows"),
            audit.value("invalid_invoice_date_rows"),
            audit.value("invalid_item_quantity_rows"),
        )
        if any(value > 0 for value in blocking_metrics) and not allow_unmapped:
            raise RuntimeError(
                "Transform blocked: invoice/receipt link, product mapping, date, or quantity issues detected. "
                "Fix source/mapping first, or rerun with --allow-unmapped for controlled testing."
            )

        if not execute:
            logger.info("Dry-run only. Add --execute to insert into target facts.")
            return AccurateOfflineSalesTransformResult(audit=audit, order_rows=0, item_rows=0)

        logger.info("Execute Accurate offline sales transform")
        order_result = conn.execute(text(insert_order_sql(ctx)))
        logger.info("Accurate offline sales order upsert finished: rows=%s", order_result.rowcount)
        conn.execute(text(f"ANALYZE {target_schema}.fact_sales_order"))

        item_result = conn.execute(text(insert_item_sql(ctx)))
        logger.info("Accurate offline sales item upsert finished: rows=%s", item_result.rowcount)
        conn.execute(text(f"ANALYZE {target_schema}.fact_sales_order_item"))

        return AccurateOfflineSalesTransformResult(
            audit=audit,
            order_rows=order_result.rowcount,
            item_rows=item_result.rowcount,
        )
    finally:
        pass


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


def source_invoice_cte(ctx: TransformContext) -> str:
    return f"""
WITH receipt_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(receipt_id), ''), 'nan'), '-') AS receipt_id,
        NULLIF(NULLIF(NULLIF(TRIM(receipt_number), ''), 'nan'), '-') AS receipt_number,
        NULLIF(NULLIF(NULLIF(TRIM(receipt_trans_date), ''), 'nan'), '-') AS receipt_trans_date_text,
        NULLIF(NULLIF(NULLIF(TRIM(receipt_cheque_date), ''), 'nan'), '-') AS receipt_cheque_date_text,
        NULLIF(NULLIF(NULLIF(TRIM(bank_id), ''), 'nan'), '-') AS bank_id,
        NULLIF(NULLIF(NULLIF(TRIM(bank_no), ''), 'nan'), '-') AS bank_no,
        NULLIF(NULLIF(NULLIF(TRIM(bank_name), ''), 'nan'), '-') AS bank_name,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_payment), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS total_payment_text,
        NULLIF(NULLIF(NULLIF(TRIM(invoice_ids), ''), 'nan'), '-') AS invoice_ids
    FROM {ctx.staging_schema}.accurate_sales_receipt
),
invoice_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(invoice_id), ''), 'nan'), '-') AS invoice_id,
        NULLIF(NULLIF(NULLIF(TRIM(invoice_number), ''), 'nan'), '-') AS invoice_number,
        NULLIF(NULLIF(NULLIF(TRIM(invoice_trans_date), ''), 'nan'), '-') AS invoice_trans_date_text,
        NULLIF(NULLIF(NULLIF(TRIM(invoice_due_date), ''), 'nan'), '-') AS invoice_due_date_text,
        NULLIF(NULLIF(NULLIF(TRIM(ship_date), ''), 'nan'), '-') AS ship_date_text,
        NULLIF(NULLIF(NULLIF(TRIM(last_payment_date), ''), 'nan'), '-') AS last_payment_date_text,
        NULLIF(NULLIF(NULLIF(TRIM(receipt_id), ''), 'nan'), '-') AS receipt_id,
        NULLIF(NULLIF(NULLIF(TRIM(receipt_number), ''), 'nan'), '-') AS receipt_number,
        NULLIF(NULLIF(NULLIF(TRIM(po_number), ''), 'nan'), '-') AS po_number,
        NULLIF(NULLIF(NULLIF(TRIM(description), ''), 'nan'), '-') AS description,
        NULLIF(NULLIF(NULLIF(TRIM(customer_id), ''), 'nan'), '-') AS accurate_customer_id,
        NULLIF(NULLIF(NULLIF(TRIM(customer_name), ''), 'nan'), '-') AS customer_name,
        NULLIF(NULLIF(NULLIF(TRIM(customer_no), ''), 'nan'), '-') AS customer_no,
        NULLIF(NULLIF(NULLIF(TRIM(shipment_id), ''), 'nan'), '-') AS shipment_id,
        NULLIF(NULLIF(NULLIF(TRIM(shipment_name), ''), 'nan'), '-') AS shipment_name,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sales_amount_base), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS sales_amount_base_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(prime_receipt), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS prime_receipt_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(cash_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS cash_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(tax1_amount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS tax1_amount_text,
        NULLIF(NULLIF(NULLIF(TRIM(taxable), ''), 'nan'), '-') AS taxable,
        NULLIF(NULLIF(NULLIF(TRIM(online_order), ''), 'nan'), '-') AS online_order,
        NULLIF(NULLIF(NULLIF(TRIM(approval_status), ''), 'nan'), '-') AS approval_status,
        NULLIF(NULLIF(NULLIF(TRIM(detail_item_count), ''), 'nan'), '-') AS detail_item_count
    FROM {ctx.staging_schema}.accurate_sales_invoice
),
normalized_invoice AS (
    SELECT
        i.*,
        CASE
            WHEN i.invoice_trans_date_text ~ '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}$'
                THEN to_date(i.invoice_trans_date_text, 'DD/MM/YYYY')
            WHEN i.invoice_trans_date_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$'
                THEN i.invoice_trans_date_text::date
            ELSE NULL
        END AS invoice_date,
        CASE
            WHEN i.last_payment_date_text ~ '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}$'
                THEN to_date(i.last_payment_date_text, 'DD/MM/YYYY')
            WHEN i.last_payment_date_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$'
                THEN i.last_payment_date_text::date
            ELSE NULL
        END AS last_payment_date,
        CASE
            WHEN i.sales_amount_base_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN i.sales_amount_base_text::numeric
            ELSE NULL
        END AS sales_amount_base,
        CASE
            WHEN i.prime_receipt_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN i.prime_receipt_text::numeric
            ELSE NULL
        END AS prime_receipt,
        CASE
            WHEN i.cash_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(i.cash_discount_text::numeric)
            ELSE 0::numeric
        END AS cash_discount,
        CASE
            WHEN i.tax1_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN i.tax1_amount_text::numeric
            ELSE 0::numeric
        END AS tax1_amount
    FROM invoice_rows i
),
joined_invoice AS (
    SELECT
        i.*,
        r.bank_id,
        r.bank_no,
        r.bank_name,
        CASE
            WHEN r.total_payment_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN r.total_payment_text::numeric
            ELSE NULL
        END AS receipt_total_payment
    FROM normalized_invoice i
    LEFT JOIN receipt_rows r
        ON r.receipt_id = i.receipt_id
)
"""


def source_item_cte(ctx: TransformContext) -> str:
    return f"""
WITH item_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(invoice_id), ''), 'nan'), '-') AS invoice_id,
        NULLIF(NULLIF(NULLIF(TRIM(invoice_number), ''), 'nan'), '-') AS invoice_number,
        NULLIF(NULLIF(NULLIF(TRIM(receipt_id), ''), 'nan'), '-') AS receipt_id,
        NULLIF(NULLIF(NULLIF(TRIM(receipt_number), ''), 'nan'), '-') AS receipt_number,
        NULLIF(NULLIF(NULLIF(TRIM(invoice_item_id), ''), 'nan'), '-') AS invoice_item_id,
        NULLIF(NULLIF(NULLIF(TRIM(seq), ''), 'nan'), '-') AS seq,
        NULLIF(NULLIF(NULLIF(TRIM(accurate_item_id), ''), 'nan'), '-') AS accurate_item_id,
        NULLIF(NULLIF(NULLIF(TRIM(accurate_item_no), ''), 'nan'), '-') AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(accurate_item_name), ''), 'nan'), '-') AS source_product_name,
        NULLIF(NULLIF(NULLIF(TRIM(accurate_item_short_name), ''), 'nan'), '-') AS source_variation_name,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(quantity), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS quantity_text,
        NULLIF(NULLIF(NULLIF(TRIM(unit_name), ''), 'nan'), '-') AS unit_name,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(unit_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS unit_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(discount_amount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS discount_amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS total_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(tax1_amount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS tax1_amount_text,
        NULLIF(NULLIF(NULLIF(TRIM(sales_order_detail_id), ''), 'nan'), '-') AS sales_order_detail_id,
        NULLIF(NULLIF(NULLIF(TRIM(delivery_order_detail_id), ''), 'nan'), '-') AS delivery_order_detail_id
    FROM {ctx.staging_schema}.accurate_sales_invoice_item
),
normalized_item AS (
    SELECT
        i.*,
        CASE
            WHEN i.quantity_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN i.quantity_text::numeric
            ELSE NULL
        END AS quantity,
        CASE
            WHEN i.unit_price_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN i.unit_price_text::numeric
            ELSE NULL
        END AS unit_price,
        CASE
            WHEN i.discount_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(i.discount_amount_text::numeric)
            ELSE 0::numeric
        END AS discount_amount,
        CASE
            WHEN i.total_price_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN i.total_price_text::numeric
            ELSE NULL
        END AS total_price,
        CASE
            WHEN i.tax1_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN i.tax1_amount_text::numeric
            ELSE 0::numeric
        END AS tax1_amount
    FROM item_rows i
),
product_matches AS (
    SELECT
        i.*,
        pm.product_id,
        pm.product_sku_alias_id,
        COALESCE(pm.unit, i.unit_name, 'PCS') AS resolved_unit
    FROM normalized_item i
    LEFT JOIN LATERAL (
        SELECT
            psa.product_id,
            psa.product_sku_alias_id,
            psa.unit,
            CASE
                WHEN LOWER(psa.sku_code) = LOWER(i.source_sku_code) THEN 1
                WHEN LOWER(psa.sku_code) = LOWER(CONCAT(i.source_sku_code, '-Off')) THEN 2
                WHEN LOWER(psa.sku_name) = LOWER(i.source_product_name) THEN 3
                WHEN LOWER(psa.sku_name) = LOWER(i.source_variation_name) THEN 4
                ELSE 9
            END AS priority
        FROM {ctx.target_schema}.product_sku_alias psa
        WHERE psa.is_active
          AND psa.source_system = 'accurate'
          AND (
            LOWER(psa.sku_code) = LOWER(i.source_sku_code)
            OR LOWER(psa.sku_code) = LOWER(CONCAT(i.source_sku_code, '-Off'))
            OR LOWER(psa.sku_name) = LOWER(i.source_product_name)
            OR LOWER(psa.sku_name) = LOWER(i.source_variation_name)
          )
        ORDER BY
            CASE WHEN psa.sales_channel_type = 'offline' THEN 0 ELSE 1 END,
            priority,
            psa.is_primary DESC,
            psa.product_sku_alias_id
        LIMIT 1
    ) pm ON TRUE
)
"""


def audit_sql(ctx: TransformContext) -> str:
    return (
        source_invoice_cte(ctx)
        + """,
"""
        + source_item_cte(ctx).split("WITH ", 1)[1]
        + """,
duplicate_invoice AS (
    SELECT invoice_number, COUNT(*) AS row_count
    FROM joined_invoice
    WHERE invoice_number IS NOT NULL
    GROUP BY invoice_number
    HAVING COUNT(*) > 1
),
duplicate_item AS (
    SELECT invoice_number, COALESCE(invoice_item_id, ''), COALESCE(source_sku_code, ''), COUNT(*) AS row_count
    FROM product_matches
    GROUP BY invoice_number, COALESCE(invoice_item_id, ''), COALESCE(source_sku_code, '')
    HAVING COUNT(*) > 1
)
SELECT 'source_receipt_rows' AS metric, COUNT(*)::bigint AS value, 'Sales receipt rows exported by Accurate audit.' AS notes
FROM receipt_rows
UNION ALL
SELECT 'source_invoice_rows', COUNT(*)::bigint, 'Linked sales invoice rows exported by Accurate audit.'
FROM joined_invoice
UNION ALL
SELECT 'source_item_rows', COUNT(*)::bigint, 'Linked sales invoice item rows exported by Accurate audit.'
FROM product_matches
UNION ALL
SELECT 'invoice_without_receipt_rows', COUNT(*)::bigint, 'Invoice rows whose receipt_id does not resolve to receipt export.'
FROM joined_invoice
WHERE receipt_id IS NOT NULL
  AND bank_name IS NULL
  AND receipt_total_payment IS NULL
UNION ALL
SELECT 'item_without_invoice_rows', COUNT(*)::bigint, 'Item rows whose invoice_number does not resolve to invoice export.'
FROM product_matches i
LEFT JOIN joined_invoice inv
    ON inv.invoice_number = i.invoice_number
WHERE inv.invoice_number IS NULL
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Item rows that do not resolve to product_sku_alias.'
FROM product_matches
WHERE product_sku_alias_id IS NULL
UNION ALL
SELECT 'invalid_invoice_date_rows', COUNT(*)::bigint, 'Invoice rows whose invoice_trans_date could not be parsed.'
FROM joined_invoice
WHERE invoice_number IS NOT NULL
  AND invoice_date IS NULL
UNION ALL
SELECT 'invalid_item_quantity_rows', COUNT(*)::bigint, 'Item rows whose quantity could not be parsed.'
FROM product_matches
WHERE quantity IS NULL
UNION ALL
SELECT 'duplicate_invoice_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra invoice rows by invoice_number.'
FROM duplicate_invoice
UNION ALL
SELECT 'duplicate_item_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra item rows by invoice/item/SKU grain.'
FROM duplicate_item
UNION ALL
SELECT 'existing_target_order_rows', COUNT(*)::bigint, 'Existing fact_sales_order rows for Accurate offline source.'
FROM """
        + ctx.target_schema
        + """.fact_sales_order
WHERE source_system = 'accurate'
  AND sales_channel_type = 'offline';
"""
    )


def insert_order_sql(ctx: TransformContext) -> str:
    return (
        source_invoice_cte(ctx)
        + f"""
, order_rows AS (
    SELECT DISTINCT ON (invoice_number)
        'accurate'::text AS source_system,
        'sales_invoice'::text AS source_order_type,
        'offline'::text AS sales_channel_type,
        CASE
            WHEN accurate_customer_id ~ '^[0-9]+$' THEN accurate_customer_id::integer
            ELSE NULL
        END AS customer_id,
        invoice_number AS external_order_id,
        receipt_number AS external_order_group_id,
        invoice_id AS external_invoice_id,
        invoice_date AS order_date,
        invoice_date::timestamp AS order_datetime,
        approval_status AS order_status,
        CASE
            WHEN COALESCE(prime_receipt, 0) >= COALESCE(sales_amount_base, 0) THEN 'paid'
            WHEN COALESCE(prime_receipt, 0) > 0 THEN 'partial'
            ELSE 'unpaid'
        END AS payment_status,
        'IDR'::text AS currency_code,
        COALESCE(sales_amount_base, 0) AS gross_order_amount,
        COALESCE(cash_discount, 0) AS discount_amount,
        0::numeric AS shipping_fee_amount,
        COALESCE(sales_amount_base, 0) AS net_order_amount,
        'accurate_sales_receipt_invoice_audit'::text AS source_file,
        invoice_id AS raw_record_id,
        CONCAT_WS(
            ' | ',
            'Loaded by scripts/transform/accurate_offline_sales.py',
            'receipt_number=' || receipt_number,
            'receipt_total_payment=' || receipt_total_payment,
            'accurate_customer_id=' || accurate_customer_id,
            'customer_name=' || customer_name,
            'customer_no=' || customer_no,
            'po_number=' || po_number,
            'description=' || description,
            'shipment=' || shipment_name,
            'bank=' || bank_name,
            'online_order=' || online_order
        ) AS notes
    FROM joined_invoice
    WHERE invoice_number IS NOT NULL
      AND invoice_date IS NOT NULL
    ORDER BY invoice_number, receipt_number
)
INSERT INTO {ctx.target_schema}.fact_sales_order (
    source_system,
    source_order_type,
    sales_channel_type,
    customer_id,
    external_order_id,
    external_order_group_id,
    external_invoice_id,
    order_date,
    order_datetime,
    order_status,
    payment_status,
    currency_code,
    gross_order_amount,
    discount_amount,
    shipping_fee_amount,
    net_order_amount,
    source_file,
    raw_record_id,
    notes
)
SELECT
    source_system,
    source_order_type,
    sales_channel_type,
    customer_id,
    external_order_id,
    external_order_group_id,
    external_invoice_id,
    order_date,
    order_datetime,
    order_status,
    payment_status,
    currency_code,
    gross_order_amount,
    discount_amount,
    shipping_fee_amount,
    net_order_amount,
    source_file,
    raw_record_id,
    notes
FROM order_rows
ON CONFLICT DO NOTHING;
"""
    )


def insert_item_sql(ctx: TransformContext) -> str:
    return (
        source_item_cte(ctx)
        + f"""
, insert_item_rows AS (
    SELECT DISTINCT ON (
        fso.sales_order_id,
        COALESCE(i.invoice_item_id, ''),
        COALESCE(i.source_sku_code, ''),
        COALESCE(i.source_product_name, '')
    )
        fso.sales_order_id,
        COALESCE(i.invoice_item_id, i.seq, MD5(CONCAT_WS('|', i.invoice_number, i.source_sku_code, i.source_product_name))) AS source_line_id,
        i.product_id,
        i.product_sku_alias_id,
        i.source_sku_code,
        i.source_product_name,
        i.source_variation_name,
        i.quantity,
        0::numeric AS quantity_returned,
        i.resolved_unit AS unit,
        i.unit_price,
        COALESCE(i.total_price, COALESCE(i.unit_price, 0) * COALESCE(i.quantity, 0)) AS gross_item_amount,
        i.discount_amount,
        COALESCE(
            i.total_price,
            COALESCE(i.unit_price, 0) * COALESCE(i.quantity, 0) - COALESCE(i.discount_amount, 0)
        ) AS net_item_amount,
        'approved'::text AS item_status,
        'accurate_sales_receipt_invoice_audit'::text AS source_file,
        i.invoice_item_id AS raw_record_id
    FROM product_matches i
    JOIN {ctx.target_schema}.fact_sales_order fso
        ON fso.source_system = 'accurate'
       AND fso.sales_channel_type = 'offline'
       AND fso.external_order_id = i.invoice_number
    WHERE i.product_sku_alias_id IS NOT NULL
      AND i.quantity IS NOT NULL
    ORDER BY
        fso.sales_order_id,
        COALESCE(i.invoice_item_id, ''),
        COALESCE(i.source_sku_code, ''),
        COALESCE(i.source_product_name, ''),
        i.seq
)
INSERT INTO {ctx.target_schema}.fact_sales_order_item (
    sales_order_id,
    source_line_id,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    source_variation_name,
    quantity,
    quantity_returned,
    unit,
    unit_price,
    gross_item_amount,
    discount_amount,
    net_item_amount,
    item_status,
    source_file,
    raw_record_id,
    notes
)
SELECT
    sales_order_id,
    source_line_id,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    source_variation_name,
    quantity,
    quantity_returned,
    unit,
    unit_price,
    gross_item_amount,
    discount_amount,
    net_item_amount,
    item_status,
    source_file,
    raw_record_id,
    'Loaded by scripts/transform/accurate_offline_sales.py'
FROM insert_item_rows
ON CONFLICT DO NOTHING;
"""
    )


def unmapped_products_sql(ctx: TransformContext) -> str:
    return (
        source_item_cte(ctx)
        + """
SELECT
    source_sku_code,
    source_product_name,
    source_variation_name,
    COUNT(*) AS row_count,
    SUM(COALESCE(quantity, 0)) AS total_quantity,
    SUM(COALESCE(total_price, COALESCE(unit_price, 0) * COALESCE(quantity, 0))) AS total_amount,
    STRING_AGG(DISTINCT invoice_number, ' | ' ORDER BY invoice_number) AS sample_invoice_numbers
FROM product_matches
WHERE product_sku_alias_id IS NULL
GROUP BY source_sku_code, source_product_name, source_variation_name
ORDER BY row_count DESC, total_amount DESC NULLS LAST;
"""
    )


def duplicate_grain_sql(ctx: TransformContext) -> str:
    return (
        source_item_cte(ctx)
        + """
SELECT
    invoice_number,
    COALESCE(invoice_item_id, '') AS invoice_item_id,
    COALESCE(source_sku_code, '') AS source_sku_code,
    COALESCE(source_product_name, '') AS source_product_name,
    COUNT(*) AS row_count
FROM product_matches
GROUP BY invoice_number, COALESCE(invoice_item_id, ''), COALESCE(source_sku_code, ''), COALESCE(source_product_name, '')
HAVING COUNT(*) > 1
ORDER BY row_count DESC, invoice_number, invoice_item_id;
"""
    )
