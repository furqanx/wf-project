-- Final publication audit for governed Lazada and Shopee adjustments.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

WITH adjustment AS (
    SELECT
        source_system,
        sales_settlement_adjustment_id,
        store_id,
        sales_order_id,
        sales_settlement_id,
        NULLIF(BTRIM(related_external_order_id), '')
            AS related_external_order_id,
        signed_adjustment_amount,
        adjustment_occurred_at
    FROM public.fact_sales_settlement_adjustment
    WHERE is_active = TRUE
      AND source_system IN ('lazada', 'shopee')
),
classified AS (
    SELECT
        adjustment.*,
        settlement.sales_order_id AS settlement_sales_order_id,
        CASE
            WHEN adjustment.sales_order_id IS NOT NULL
             AND adjustment.sales_settlement_id IS NOT NULL
                THEN 'order_and_settlement'
            WHEN adjustment.sales_order_id IS NOT NULL
                THEN 'order_only'
            WHEN adjustment.sales_settlement_id IS NOT NULL
                THEN 'settlement_only'
            WHEN adjustment.related_external_order_id IS NOT NULL
             AND adjustment.store_id IS NOT NULL
             AND adjustment.adjustment_occurred_at IS NOT NULL
                THEN 'source_order_unavailable_store_period'
            WHEN adjustment.store_id IS NOT NULL
             AND adjustment.adjustment_occurred_at IS NOT NULL
                THEN 'store_period_only'
            ELSE 'unresolved'
        END AS governed_attribution
    FROM adjustment
    LEFT JOIN public.fact_sales_settlement settlement
      ON settlement.sales_settlement_id = adjustment.sales_settlement_id
)
SELECT
    source_system,
    governed_attribution,
    COUNT(*) AS adjustment_rows,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount
FROM classified
GROUP BY source_system, governed_attribution
ORDER BY source_system, governed_attribution;

WITH adjustment AS (
    SELECT adjustment.*, settlement.sales_order_id AS settlement_sales_order_id
    FROM public.fact_sales_settlement_adjustment adjustment
    LEFT JOIN public.fact_sales_settlement settlement
      ON settlement.sales_settlement_id = adjustment.sales_settlement_id
    WHERE adjustment.is_active = TRUE
      AND adjustment.source_system IN ('lazada', 'shopee')
)
SELECT
    COUNT(*) FILTER (
        WHERE sales_order_id IS NOT NULL
          AND settlement_sales_order_id IS NOT NULL
          AND sales_order_id <> settlement_sales_order_id
    ) AS order_settlement_mismatch_rows,
    COUNT(*) FILTER (
        WHERE sales_order_id IS NULL
          AND sales_settlement_id IS NULL
          AND (store_id IS NULL OR adjustment_occurred_at IS NULL)
    ) AS unlinked_without_store_period_rows,
    COUNT(*) FILTER (
        WHERE source_system = 'shopee'
          AND sales_order_id IS NULL
          AND sales_settlement_id IS NOT NULL
          AND settlement_sales_order_id IS NOT NULL
    ) AS shopee_safe_link_not_propagated_rows
FROM adjustment;
