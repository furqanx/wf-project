-- Diagnose marketplace-cost components repeated across multiple source files.
-- Read-only: all working objects are temporary and rolled back.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_fee_cost_rows ON COMMIT DROP AS
SELECT
    source_system,
    store_id,
    sales_order_id,
    sales_settlement_id,
    external_order_id,
    external_order_item_id,
    source_sku_code,
    fee_type_id,
    fee_code,
    fee_name,
    fee_grain_type,
    raw_fee_name,
    raw_fee_amount,
    signed_fee_amount,
    marketplace_cost_amount,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id
FROM public.vw_sales_marketplace_fee_semantic
WHERE include_in_marketplace_cost;

CREATE INDEX ON tmp_fee_cost_rows (
    source_system,
    store_id,
    external_order_id,
    fee_type_id
);
ANALYZE tmp_fee_cost_rows;

CREATE TEMP TABLE tmp_overlap_key ON COMMIT DROP AS
SELECT
    source_system,
    store_id,
    external_order_id,
    fee_type_id,
    COUNT(DISTINCT source_file) AS source_file_count,
    COUNT(*) AS fee_rows,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_fee_cost_rows
GROUP BY 1, 2, 3, 4
HAVING COUNT(DISTINCT source_file) > 1;

CREATE INDEX ON tmp_overlap_key (
    source_system,
    store_id,
    external_order_id,
    fee_type_id
);
ANALYZE tmp_overlap_key;

-- A. Size and value of the overlap population.
SELECT
    rows.source_system,
    rows.fee_type_id,
    rows.fee_code,
    COUNT(DISTINCT (
        rows.store_id,
        rows.external_order_id,
        rows.fee_type_id
    )) AS affected_order_components,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT rows.source_file) AS source_files,
    SUM(rows.marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_fee_cost_rows rows
JOIN tmp_overlap_key keys
  ON keys.source_system = rows.source_system
 AND keys.store_id IS NOT DISTINCT FROM rows.store_id
 AND keys.external_order_id = rows.external_order_id
 AND keys.fee_type_id = rows.fee_type_id
GROUP BY 1, 2, 3
ORDER BY 1, marketplace_cost_amount DESC, 2;

-- B. Source-file families participating in overlap. Timestamp suffixes are
-- normalized so repeated monthly exports can be compared as one family.
WITH source_family AS (
    SELECT
        rows.*,
        REGEXP_REPLACE(
            rows.source_file,
            '([_-])[0-9]{8}([_-])[0-9]{6}(\.[^.]+)?$',
            '\3'
        ) AS source_file_family
    FROM tmp_fee_cost_rows rows
    JOIN tmp_overlap_key keys
      ON keys.source_system = rows.source_system
     AND keys.store_id IS NOT DISTINCT FROM rows.store_id
     AND keys.external_order_id = rows.external_order_id
     AND keys.fee_type_id = rows.fee_type_id
)
SELECT
    source_system,
    fee_type_id,
    fee_code,
    source_file_family,
    source_sheet,
    fee_grain_type,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT external_order_id) AS orders,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM source_family
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY 1, 2, fee_rows DESC, source_file_family, source_sheet;

\copy (WITH source_family AS (SELECT rows.*, REGEXP_REPLACE(rows.source_file, '([_-])[0-9]{8}([_-])[0-9]{6}(\.[^.]+)?$', '\3') AS source_file_family FROM tmp_fee_cost_rows rows JOIN tmp_overlap_key keys ON keys.source_system = rows.source_system AND keys.store_id IS NOT DISTINCT FROM rows.store_id AND keys.external_order_id = rows.external_order_id AND keys.fee_type_id = rows.fee_type_id) SELECT source_system, fee_type_id, fee_code, source_file_family, source_sheet, fee_grain_type, COUNT(*) AS fee_rows, COUNT(DISTINCT external_order_id) AS orders, SUM(marketplace_cost_amount) AS marketplace_cost_amount FROM source_family GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY 1, 2, fee_rows DESC, source_file_family, source_sheet) TO '/tmp/sales_marketplace_fee_overlap_source_family.csv' WITH (FORMAT CSV, HEADER TRUE)

-- C. Complete row-level evidence for deciding source priority/deduplication.
\copy (SELECT rows.source_system, rows.store_id, rows.sales_order_id, rows.sales_settlement_id, rows.external_order_id, rows.external_order_item_id, rows.source_sku_code, rows.fee_type_id, rows.fee_code, rows.fee_name, rows.fee_grain_type, rows.raw_fee_name, rows.raw_fee_amount, rows.signed_fee_amount, rows.marketplace_cost_amount, rows.source_file, rows.source_sheet, rows.source_row_number, rows.raw_record_id FROM tmp_fee_cost_rows rows JOIN tmp_overlap_key keys ON keys.source_system = rows.source_system AND keys.store_id IS NOT DISTINCT FROM rows.store_id AND keys.external_order_id = rows.external_order_id AND keys.fee_type_id = rows.fee_type_id ORDER BY rows.source_system, rows.fee_type_id, rows.store_id, rows.external_order_id, rows.source_file, rows.source_sheet, rows.source_row_number) TO '/tmp/sales_marketplace_fee_overlap_detail.csv' WITH (FORMAT CSV, HEADER TRUE)

-- D. Exact-value repetition across source files. A high count is strong
-- evidence of duplicated exports; differing values require source semantics.
SELECT
    comparison.source_system,
    comparison.fee_type_id,
    comparison.fee_code,
    COUNT(*) FILTER (WHERE comparison.distinct_amounts = 1) AS exact_amount_keys,
    COUNT(*) FILTER (WHERE comparison.distinct_amounts > 1) AS differing_amount_keys,
    COUNT(*) AS overlap_keys
FROM (
    SELECT
        source_system,
        store_id,
        external_order_id,
        fee_type_id,
        MAX(fee_code) AS fee_code,
        COUNT(DISTINCT marketplace_cost_amount) AS distinct_amounts
    FROM tmp_fee_cost_rows
    GROUP BY 1, 2, 3, 4
    HAVING COUNT(DISTINCT source_file) > 1
) comparison
GROUP BY 1, 2, 3
ORDER BY 1, 2;

ROLLBACK;
