-- Verify marketplace-fee overlap remediation.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_fee_semantic ON COMMIT DROP AS
SELECT
    source_system,
    store_id,
    external_order_id,
    fee_type_id,
    fee_code,
    economic_role,
    include_in_marketplace_cost,
    marketplace_cost_behavior,
    fee_grain_type,
    source_file,
    source_sheet,
    is_marketplace_cost_selected,
    marketplace_cost_exclusion_reason,
    marketplace_cost_amount
FROM public.vw_sales_marketplace_fee_semantic
WHERE include_in_marketplace_cost
   OR economic_role = 'unclassified'
   OR (source_system = 'shopee' AND fee_code IN (
       'biaya_proses_pesanan',
       'biaya_proses_pesanan_per_produk_prorata'
   ));

-- A. Selected official cost and excluded records by reason.
SELECT
    source_system,
    COALESCE(marketplace_cost_exclusion_reason, 'selected') AS selection_status,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT external_order_id) AS orders,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_fee_semantic
WHERE include_in_marketplace_cost
GROUP BY 1, 2
ORDER BY 1, 2;

-- B. No selected order-level fee component may occur more than once.
WITH selected_order_fee AS (
    SELECT
        source_system,
        store_id,
        external_order_id,
        fee_type_id,
        COUNT(*) AS selected_rows,
        COUNT(DISTINCT source_file) AS selected_source_files
    FROM tmp_fee_semantic
    WHERE is_marketplace_cost_selected
      AND fee_grain_type = 'order_level'
    GROUP BY 1, 2, 3, 4
)
SELECT
    source_system,
    COUNT(*) FILTER (WHERE selected_source_files > 1) AS multi_source_violations,
    COUNT(*) FILTER (WHERE selected_rows > 1) AS repeated_order_fee_keys
FROM selected_order_fee
GROUP BY 1
ORDER BY 1;

-- C. Shopee processing-fee total uses only the order-level representation.
SELECT
    fee_code,
    economic_role,
    fee_grain_type,
    source_sheet,
    is_marketplace_cost_selected,
    marketplace_cost_exclusion_reason,
    COUNT(*) AS fee_rows,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_fee_semantic
WHERE source_system = 'shopee'
  AND fee_code IN (
      'biaya_proses_pesanan',
      'biaya_proses_pesanan_per_produk_prorata'
  )
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY 1, 3, 4, 5;

-- D. Publication guardrails. Every result must be zero.
SELECT
    COUNT(*) FILTER (
        WHERE economic_role = 'unclassified'
    ) AS unclassified_observed_rows,
    COUNT(*) FILTER (
        WHERE is_marketplace_cost_selected
          AND marketplace_cost_amount IS NULL
    ) AS selected_without_amount_rows,
    COUNT(*) FILTER (
        WHERE NOT is_marketplace_cost_selected
          AND marketplace_cost_amount IS NOT NULL
    ) AS excluded_with_amount_rows,
    COUNT(*) FILTER (
        WHERE is_marketplace_cost_selected
          AND economic_role NOT IN ('platform_fee', 'cost_reversal')
    ) AS invalid_selected_role_rows
FROM tmp_fee_semantic;

ROLLBACK;
