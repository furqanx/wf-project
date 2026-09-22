-- Read-only canonical valid-order marketplace fee coverage.

\pset pager off
\set ON_ERROR_STOP on

SET statement_timeout = '15min';
SET lock_timeout = '10s';

WITH order_resolution AS (
    SELECT
        candidate.sales_order_id AS source_sales_order_id,
        canonical.sales_order_id AS canonical_sales_order_id
    FROM public.vw_sales_order_channel_classification candidate
    JOIN public.vw_sales_order_channel_classification canonical
        ON canonical.source_system = candidate.source_system
       AND canonical.external_order_id = candidate.external_order_id
       AND COALESCE(canonical.net_order_amount, 0) = COALESCE(candidate.net_order_amount, 0)
       AND canonical.product_quantity_signature = candidate.product_quantity_signature
       AND canonical.is_analytics_included = TRUE
    WHERE candidate.source_system IN ('shopee', 'lazada', 'tiktok_tokopedia')
), eligible_orders AS (
    SELECT
        sales_order_id,
        source_system,
        store_id,
        order_date
    FROM public.vw_sales_semantic_order
    WHERE analytics_channel_type = 'online'
      AND valid_order_count = 1
), fee_by_order AS (
    SELECT
        resolution.canonical_sales_order_id AS sales_order_id,
        COUNT(*) AS fee_rows,
        SUM(fees.signed_fee_amount) AS signed_fee_amount
    FROM public.fact_sales_settlement_fee_detail fees
    JOIN order_resolution resolution
        ON resolution.source_sales_order_id = fees.sales_order_id
    WHERE fees.is_active = TRUE
      AND fees.sales_order_id IS NOT NULL
    GROUP BY resolution.canonical_sales_order_id
)
SELECT
    orders.source_system,
    COUNT(*) AS eligible_orders,
    COUNT(fees.sales_order_id) AS orders_with_fee,
    COUNT(*) - COUNT(fees.sales_order_id) AS orders_with_unknown_fee,
    ROUND(
        100.0 * COUNT(fees.sales_order_id) / NULLIF(COUNT(*), 0),
        2
    ) AS fee_coverage_pct,
    SUM(COALESCE(fees.fee_rows, 0)) AS fee_rows,
    SUM(fees.signed_fee_amount) AS signed_fee_amount
FROM eligible_orders orders
LEFT JOIN fee_by_order fees
    ON fees.sales_order_id = orders.sales_order_id
GROUP BY orders.source_system
ORDER BY orders.source_system;
