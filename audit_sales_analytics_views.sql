-- Reconciliation checks for create_sales_analytics_views.sql.

WITH canonical AS (
    SELECT
        COUNT(*) AS order_rows,
        SUM(net_order_amount) AS revenue
    FROM public.vw_sales_order_analytics
),
summary AS (
    SELECT
        COUNT(*) AS order_rows,
        SUM(order_revenue) AS revenue
    FROM public.vw_sales_order_summary
)
SELECT
    canonical.order_rows AS canonical_order_rows,
    summary.order_rows AS summary_order_rows,
    summary.order_rows - canonical.order_rows AS order_row_delta,
    canonical.revenue AS canonical_revenue,
    summary.revenue AS summary_revenue,
    summary.revenue - canonical.revenue AS revenue_delta
FROM canonical
CROSS JOIN summary;

SELECT
    sales_order_id,
    COUNT(*) AS row_count
FROM public.vw_sales_order_summary
GROUP BY sales_order_id
HAVING COUNT(*) > 1
ORDER BY row_count DESC, sales_order_id;

WITH canonical_items AS (
    SELECT
        COUNT(*) AS item_rows,
        SUM(quantity) AS units_sold,
        SUM(net_item_amount) AS item_net_amount
    FROM public.vw_sales_order_item_analytics
),
product_daily AS (
    SELECT
        SUM(item_row_count) AS item_rows,
        SUM(units_sold) AS units_sold,
        SUM(item_net_amount) AS item_net_amount
    FROM public.vw_sales_product_daily
)
SELECT
    canonical_items.item_rows AS canonical_item_rows,
    product_daily.item_rows AS product_daily_item_rows,
    product_daily.item_rows - canonical_items.item_rows AS item_row_delta,
    canonical_items.units_sold AS canonical_units_sold,
    product_daily.units_sold AS product_daily_units_sold,
    product_daily.units_sold - canonical_items.units_sold AS units_sold_delta,
    canonical_items.item_net_amount AS canonical_item_net_amount,
    product_daily.item_net_amount AS product_daily_item_net_amount,
    product_daily.item_net_amount - canonical_items.item_net_amount AS item_amount_delta
FROM canonical_items
CROSS JOIN product_daily;

WITH summary AS (
    SELECT COUNT(*) AS order_rows, SUM(order_revenue) AS revenue
    FROM public.vw_sales_order_summary
),
daily AS (
    SELECT SUM(order_count) AS order_rows, SUM(revenue) AS revenue
    FROM public.vw_sales_trend_daily
),
monthly AS (
    SELECT SUM(order_count) AS order_rows, SUM(revenue) AS revenue
    FROM public.vw_sales_trend_monthly
)
SELECT
    summary.order_rows AS summary_order_rows,
    daily.order_rows AS daily_order_rows,
    monthly.order_rows AS monthly_order_rows,
    daily.order_rows - summary.order_rows AS daily_order_delta,
    monthly.order_rows - summary.order_rows AS monthly_order_delta,
    summary.revenue AS summary_revenue,
    daily.revenue AS daily_revenue,
    monthly.revenue AS monthly_revenue,
    daily.revenue - summary.revenue AS daily_revenue_delta,
    monthly.revenue - summary.revenue AS monthly_revenue_delta
FROM summary
CROSS JOIN daily
CROSS JOIN monthly;

WITH offline_summary AS (
    SELECT COUNT(*) AS order_rows, SUM(order_revenue) AS revenue
    FROM public.vw_sales_order_summary
    WHERE analytics_channel_type IN ('offline_b2b', 'offline_retail')
),
customers AS (
    SELECT SUM(order_count) AS order_rows, SUM(revenue) AS revenue
    FROM public.vw_sales_customer_performance
)
SELECT
    offline_summary.order_rows AS offline_order_rows,
    customers.order_rows AS customer_order_rows,
    customers.order_rows - offline_summary.order_rows AS order_row_delta,
    offline_summary.revenue AS offline_revenue,
    customers.revenue AS customer_revenue,
    customers.revenue - offline_summary.revenue AS revenue_delta
FROM offline_summary
CROSS JOIN customers;

SELECT
    analytics_channel_type,
    source_system,
    COUNT(*) AS order_rows,
    SUM(order_revenue) AS revenue,
    SUM(units_sold) AS units_sold
FROM public.vw_sales_order_summary
GROUP BY analytics_channel_type, source_system
ORDER BY analytics_channel_type, source_system;

