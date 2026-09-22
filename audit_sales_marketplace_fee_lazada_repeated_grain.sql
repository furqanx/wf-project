-- Diagnose repeated selected Lazada fee rows at order/item/type grain.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_lazada_selected_fee ON COMMIT DROP AS
SELECT
    store_id,
    sales_order_id,
    sales_settlement_id,
    external_order_id,
    external_order_item_id,
    source_sku_code,
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
WHERE source_system = 'lazada'
  AND is_marketplace_cost_selected;

CREATE TEMP TABLE tmp_lazada_repeated_key ON COMMIT DROP AS
SELECT
    store_id,
    external_order_id,
    COALESCE(external_order_item_id, '') AS external_order_item_id,
    COALESCE(source_sku_code, '') AS source_sku_code,
    fee_type_id,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT marketplace_cost_amount) AS distinct_amounts,
    COUNT(DISTINCT raw_fee_name) AS raw_fee_names,
    COUNT(DISTINCT source_file) AS source_files,
    COUNT(DISTINCT sales_settlement_id) AS settlement_ids,
    SUM(marketplace_cost_amount) AS summed_cost_amount,
    MAX(marketplace_cost_amount) AS maximum_cost_amount
FROM tmp_lazada_selected_fee
GROUP BY 1, 2, 3, 4, 5
HAVING COUNT(*) > 1;

-- A. Repetition characteristics by fee type.
SELECT
    rows.fee_type_id,
    rows.fee_code,
    rows.fee_name,
    COUNT(*) AS repeated_keys,
    COUNT(*) FILTER (WHERE keys.distinct_amounts = 1) AS exact_amount_keys,
    COUNT(*) FILTER (WHERE keys.distinct_amounts > 1) AS differing_amount_keys,
    COUNT(*) FILTER (WHERE keys.raw_fee_names > 1) AS multiple_raw_name_keys,
    COUNT(*) FILTER (WHERE keys.source_files > 1) AS cross_file_keys,
    COUNT(*) FILTER (WHERE keys.settlement_ids > 1) AS cross_settlement_keys,
    SUM(keys.fee_rows) AS fee_rows,
    SUM(keys.summed_cost_amount) AS summed_cost_amount,
    SUM(keys.maximum_cost_amount) AS one_maximum_per_key_amount
FROM tmp_lazada_repeated_key keys
JOIN (
    SELECT DISTINCT fee_type_id, fee_code, fee_name
    FROM tmp_lazada_selected_fee
) rows USING (fee_type_id)
GROUP BY 1, 2, 3
ORDER BY summed_cost_amount DESC, rows.fee_type_id;

-- B. Raw fee names behind each repeated canonical fee type. VAT is expected
-- to repeat when it is attached to several distinct source fee components.
SELECT
    rows.fee_type_id,
    rows.fee_code,
    rows.raw_fee_name,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT rows.external_order_id) AS orders,
    SUM(rows.marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_lazada_selected_fee rows
JOIN tmp_lazada_repeated_key keys
  ON keys.store_id IS NOT DISTINCT FROM rows.store_id
 AND keys.external_order_id = rows.external_order_id
 AND keys.external_order_item_id = COALESCE(rows.external_order_item_id, '')
 AND keys.source_sku_code = COALESCE(rows.source_sku_code, '')
 AND keys.fee_type_id = rows.fee_type_id
GROUP BY 1, 2, 3
ORDER BY 1, marketplace_cost_amount DESC, 3;

\copy (SELECT rows.* FROM tmp_lazada_selected_fee rows JOIN tmp_lazada_repeated_key keys ON keys.store_id IS NOT DISTINCT FROM rows.store_id AND keys.external_order_id = rows.external_order_id AND keys.external_order_item_id = COALESCE(rows.external_order_item_id, '') AND keys.source_sku_code = COALESCE(rows.source_sku_code, '') AND keys.fee_type_id = rows.fee_type_id ORDER BY rows.fee_type_id, rows.store_id, rows.external_order_id, rows.external_order_item_id, rows.source_row_number) TO '/tmp/sales_marketplace_fee_lazada_repeated_grain_detail.csv' WITH (FORMAT CSV, HEADER TRUE)

ROLLBACK;

