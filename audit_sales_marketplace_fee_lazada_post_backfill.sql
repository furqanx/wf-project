-- Validate Lazada marketplace-fee completeness after the row-alias fix.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_lazada_fee_semantic ON COMMIT DROP AS
SELECT *
FROM public.vw_sales_marketplace_fee_semantic
WHERE source_system = 'lazada';

-- A. Economic-role totals after semantic selection.
SELECT
    economic_role,
    COUNT(*) AS raw_fee_rows,
    COUNT(*) FILTER (WHERE is_marketplace_cost_selected) AS selected_fee_rows,
    COUNT(DISTINCT external_order_id) FILTER (
        WHERE is_marketplace_cost_selected
    ) AS selected_orders,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_lazada_fee_semantic
GROUP BY 1
ORDER BY 1;

-- B. Fee-type detail. This must contain commission, transaction, processing,
-- promotion program charges, and reversals in addition to VAT.
SELECT
    fee_type_id,
    fee_code,
    fee_name,
    economic_role,
    COUNT(*) AS raw_fee_rows,
    COUNT(*) FILTER (WHERE is_marketplace_cost_selected) AS selected_fee_rows,
    COUNT(DISTINCT external_order_id) FILTER (
        WHERE is_marketplace_cost_selected
    ) AS selected_orders,
    SUM(signed_fee_amount) AS signed_amount,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_lazada_fee_semantic
GROUP BY 1, 2, 3, 4
ORDER BY ABS(COALESCE(SUM(marketplace_cost_amount), 0)) DESC, fee_type_id;

-- C. Compare active source aliases with rows loaded into the fee fact.
WITH expected AS (
    SELECT
        aliases.fee_type_id,
        MAX(types.fee_code) AS fee_code,
        MAX(types.fee_name) AS fee_name,
        SUM(COALESCE(aliases.non_zero_rows, 0)) AS audited_source_non_zero_rows
    FROM public.fee_type_alias aliases
    JOIN public.fee_type types
      ON types.fee_type_id = aliases.fee_type_id
    WHERE aliases.source_system = 'lazada'
      AND aliases.source_phase = 'income'
      AND aliases.is_active
      AND types.is_active
      AND types.include_in_fee_fact
    GROUP BY aliases.fee_type_id
),
loaded AS (
    SELECT
        fee_type_id,
        COUNT(*) AS loaded_fact_rows
    FROM public.fact_sales_settlement_fee_detail
    WHERE source_system = 'lazada'
      AND is_active
    GROUP BY fee_type_id
)
SELECT
    expected.fee_type_id,
    expected.fee_code,
    expected.fee_name,
    expected.audited_source_non_zero_rows,
    COALESCE(loaded.loaded_fact_rows, 0) AS loaded_fact_rows,
    CASE
        WHEN expected.audited_source_non_zero_rows > 0
         AND COALESCE(loaded.loaded_fact_rows, 0) = 0
            THEN 'missing_from_fact'
        ELSE 'present'
    END AS load_status
FROM expected
LEFT JOIN loaded USING (fee_type_id)
ORDER BY load_status DESC, expected.fee_code;

-- D. Selected order-level component uniqueness. Item-level VAT can legitimately
-- repeat because Lazada emits one VAT value for each underlying fee component.
WITH selected_grain AS (
    SELECT
        store_id,
        external_order_id,
        COALESCE(external_order_item_id, '') AS external_order_item_id,
        COALESCE(source_sku_code, '') AS source_sku_code,
        fee_type_id,
        COUNT(*) AS selected_rows,
        COUNT(DISTINCT source_file) AS selected_source_files
    FROM tmp_lazada_fee_semantic
    WHERE is_marketplace_cost_selected
      AND fee_grain_type = 'order_level'
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    COUNT(*) FILTER (WHERE selected_rows > 1) AS repeated_selected_grains,
    COUNT(*) FILTER (WHERE selected_source_files > 1) AS multi_source_selected_grains
FROM selected_grain;

-- E. Publication guardrails. Every value must be zero.
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
FROM tmp_lazada_fee_semantic;

ROLLBACK;
