-- Reconciliation checks for create_sales_semantic_layer.sql.

WITH source AS (
    SELECT
        COUNT(*) AS order_rows,
        SUM(CASE WHEN is_canceled THEN 0 ELSE 1 END) AS valid_order_rows,
        SUM(CASE WHEN is_canceled THEN 0 ELSE order_revenue END) AS recognized_revenue,
        SUM(CASE WHEN is_canceled THEN 0 ELSE units_sold END) AS recognized_units_sold
    FROM public.vw_sales_order_summary
),
semantic AS (
    SELECT
        COUNT(*) AS order_rows,
        SUM(valid_order_count) AS valid_order_rows,
        SUM(recognized_revenue) AS recognized_revenue,
        SUM(recognized_units_sold) AS recognized_units_sold
    FROM public.vw_sales_semantic_order
)
SELECT
    semantic.order_rows - source.order_rows AS order_row_delta,
    semantic.valid_order_rows - source.valid_order_rows AS valid_order_delta,
    semantic.recognized_revenue - source.recognized_revenue AS revenue_delta,
    semantic.recognized_units_sold - source.recognized_units_sold AS units_delta
FROM source
CROSS JOIN semantic;

WITH orders AS (
    SELECT
        SUM(canonical_order_count) AS canonical_order_count,
        SUM(valid_order_count) AS valid_order_count,
        SUM(recognized_revenue) AS recognized_revenue,
        SUM(net_revenue_after_returns) AS net_revenue_after_returns,
        SUM(delivered_order_count) AS delivered_order_count
    FROM public.vw_sales_semantic_order
),
daily AS (
    SELECT
        SUM(canonical_order_count) AS canonical_order_count,
        SUM(valid_order_count) AS valid_order_count,
        SUM(recognized_revenue) AS recognized_revenue,
        SUM(net_revenue_after_returns) AS net_revenue_after_returns,
        SUM(delivered_order_count) AS delivered_order_count
    FROM public.vw_sales_semantic_daily
),
monthly AS (
    SELECT
        SUM(canonical_order_count) AS canonical_order_count,
        SUM(valid_order_count) AS valid_order_count,
        SUM(recognized_revenue) AS recognized_revenue,
        SUM(net_revenue_after_returns) AS net_revenue_after_returns,
        SUM(delivered_order_count) AS delivered_order_count
    FROM public.vw_sales_semantic_monthly
)
SELECT
    daily.canonical_order_count - orders.canonical_order_count AS daily_order_delta,
    monthly.canonical_order_count - orders.canonical_order_count AS monthly_order_delta,
    daily.valid_order_count - orders.valid_order_count AS daily_valid_order_delta,
    monthly.valid_order_count - orders.valid_order_count AS monthly_valid_order_delta,
    daily.recognized_revenue - orders.recognized_revenue AS daily_revenue_delta,
    monthly.recognized_revenue - orders.recognized_revenue AS monthly_revenue_delta,
    daily.net_revenue_after_returns - orders.net_revenue_after_returns AS daily_net_revenue_delta,
    monthly.net_revenue_after_returns - orders.net_revenue_after_returns AS monthly_net_revenue_delta,
    daily.delivered_order_count - orders.delivered_order_count AS daily_delivered_delta,
    monthly.delivered_order_count - orders.delivered_order_count AS monthly_delivered_delta
FROM orders
CROSS JOIN daily
CROSS JOIN monthly;

SELECT
    analytics_channel_type,
    source_system,
    SUM(canonical_order_count) AS canonical_orders,
    SUM(valid_order_count) AS valid_orders,
    SUM(canceled_order_count) AS canceled_orders,
    SUM(recognized_revenue) AS recognized_revenue,
    SUM(recognized_refund_amount) AS recognized_refund_amount,
    SUM(net_revenue_after_returns) AS net_revenue_after_returns,
    SUM(recognized_units_sold) AS recognized_units_sold,
    SUM(completed_return_order_count) AS returned_orders,
    SUM(fulfillment_eligible_order_count) AS fulfillment_eligible_orders,
    SUM(fulfillment_matched_order_count) AS fulfillment_matched_orders,
    SUM(delivered_order_count) AS delivered_orders
FROM public.vw_sales_semantic_order
GROUP BY analytics_channel_type, source_system
ORDER BY analytics_channel_type, source_system;

SELECT
    COUNT(*) FILTER (
        WHERE analytics_channel_type <> 'online'
          AND fulfillment_eligible_order_count <> 0
    ) AS offline_fulfillment_eligible_violations,
    COUNT(*) FILTER (
        WHERE is_canceled
          AND (valid_order_count <> 0 OR recognized_revenue <> 0 OR recognized_units_sold <> 0)
    ) AS canceled_order_metric_violations,
    COUNT(*) FILTER (
        WHERE NOT is_canceled
          AND recognized_revenue <> order_revenue
    ) AS valid_order_revenue_violations
FROM public.vw_sales_semantic_order;

