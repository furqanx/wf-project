-- Diagnose repeated selected order-level marketplace fee components.
-- Read-only; exports compact summaries and row evidence to /tmp.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_selected_order_fee ON COMMIT DROP AS
SELECT
    source_system,
    store_id,
    sales_order_id,
    sales_settlement_id,
    external_order_id,
    fee_type_id,
    fee_code,
    fee_name,
    raw_fee_name,
    raw_fee_amount,
    signed_fee_amount,
    marketplace_cost_amount,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id
FROM public.vw_sales_marketplace_fee_semantic
WHERE is_marketplace_cost_selected
  AND fee_grain_type = 'order_level';

CREATE TEMP TABLE tmp_repeated_order_fee_key ON COMMIT DROP AS
SELECT
    source_system,
    store_id,
    external_order_id,
    fee_type_id,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT marketplace_cost_amount) AS distinct_amounts,
    COUNT(DISTINCT source_sheet) AS source_sheets,
    COUNT(DISTINCT sales_settlement_id) AS settlement_ids,
    SUM(marketplace_cost_amount) AS summed_cost_amount,
    MAX(marketplace_cost_amount) AS maximum_cost_amount
FROM tmp_selected_order_fee
GROUP BY 1, 2, 3, 4
HAVING COUNT(*) > 1;

-- A. Is repetition exact, split-valued, cross-sheet, or cross-settlement?
SELECT
    rows.source_system,
    rows.fee_type_id,
    rows.fee_code,
    COUNT(*) AS repeated_keys,
    COUNT(*) FILTER (WHERE keys.distinct_amounts = 1) AS exact_amount_keys,
    COUNT(*) FILTER (WHERE keys.distinct_amounts > 1) AS differing_amount_keys,
    COUNT(*) FILTER (WHERE keys.source_sheets > 1) AS cross_sheet_keys,
    COUNT(*) FILTER (WHERE keys.settlement_ids > 1) AS cross_settlement_keys,
    SUM(keys.fee_rows) AS fee_rows,
    SUM(keys.summed_cost_amount) AS summed_cost_amount,
    SUM(keys.maximum_cost_amount) AS one_maximum_per_key_amount
FROM tmp_repeated_order_fee_key keys
JOIN (
    SELECT DISTINCT source_system, store_id, external_order_id, fee_type_id, fee_code
    FROM tmp_selected_order_fee
) rows
  ON rows.source_system = keys.source_system
 AND rows.store_id IS NOT DISTINCT FROM keys.store_id
 AND rows.external_order_id = keys.external_order_id
 AND rows.fee_type_id = keys.fee_type_id
GROUP BY 1, 2, 3
ORDER BY 1, summed_cost_amount DESC, 2;

\copy (SELECT rows.source_system, rows.fee_type_id, rows.fee_code, COUNT(*) AS repeated_keys, COUNT(*) FILTER (WHERE keys.distinct_amounts = 1) AS exact_amount_keys, COUNT(*) FILTER (WHERE keys.distinct_amounts > 1) AS differing_amount_keys, COUNT(*) FILTER (WHERE keys.source_sheets > 1) AS cross_sheet_keys, COUNT(*) FILTER (WHERE keys.settlement_ids > 1) AS cross_settlement_keys, SUM(keys.fee_rows) AS fee_rows, SUM(keys.summed_cost_amount) AS summed_cost_amount, SUM(keys.maximum_cost_amount) AS one_maximum_per_key_amount FROM tmp_repeated_order_fee_key keys JOIN (SELECT DISTINCT source_system, store_id, external_order_id, fee_type_id, fee_code FROM tmp_selected_order_fee) rows ON rows.source_system = keys.source_system AND rows.store_id IS NOT DISTINCT FROM keys.store_id AND rows.external_order_id = keys.external_order_id AND rows.fee_type_id = keys.fee_type_id GROUP BY 1, 2, 3 ORDER BY 1, summed_cost_amount DESC, 2) TO '/tmp/sales_marketplace_fee_repeated_order_summary.csv' WITH (FORMAT CSV, HEADER TRUE)

-- B. Sheet/file distribution helps distinguish duplicate exports from genuine
-- source component rows.
SELECT
    rows.source_system,
    rows.fee_type_id,
    rows.fee_code,
    rows.source_sheet,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT rows.external_order_id) AS orders,
    SUM(rows.marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_selected_order_fee rows
JOIN tmp_repeated_order_fee_key keys
  ON keys.source_system = rows.source_system
 AND keys.store_id IS NOT DISTINCT FROM rows.store_id
 AND keys.external_order_id = rows.external_order_id
 AND keys.fee_type_id = rows.fee_type_id
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, fee_rows DESC, 4;

-- C. Complete evidence for repeated keys.
\copy (SELECT rows.* FROM tmp_selected_order_fee rows JOIN tmp_repeated_order_fee_key keys ON keys.source_system = rows.source_system AND keys.store_id IS NOT DISTINCT FROM rows.store_id AND keys.external_order_id = rows.external_order_id AND keys.fee_type_id = rows.fee_type_id ORDER BY rows.source_system, rows.fee_type_id, rows.store_id, rows.external_order_id, rows.source_sheet, rows.source_row_number) TO '/tmp/sales_marketplace_fee_repeated_order_detail.csv' WITH (FORMAT CSV, HEADER TRUE)

ROLLBACK;

