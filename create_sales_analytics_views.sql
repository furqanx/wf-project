-- Sales analytics datasets built on the canonical channel views.
--
-- Revenue rule:
-- - Order, channel, customer, and trend revenue comes from
--   vw_sales_order_analytics.net_order_amount.
-- - Product views expose item values as item_* metrics. They are not the
--   official order revenue because item and header values can differ.
--
-- Safe to rerun. Source facts and canonical channel views are not modified.

BEGIN;

CREATE OR REPLACE VIEW public.vw_sales_order_summary AS
WITH item_summary AS (
    SELECT
        sales_order_id,
        COUNT(*) AS item_rows,
        COUNT(DISTINCT product_id) AS distinct_products,
        SUM(quantity) AS units_sold,
        SUM(gross_item_amount) AS item_gross_amount,
        SUM(discount_amount) AS item_discount_amount,
        SUM(net_item_amount) AS item_net_amount
    FROM public.vw_sales_order_item_analytics
    GROUP BY sales_order_id
)
SELECT
    fso.sales_order_id,
    fso.source_system,
    fso.analytics_channel_type,
    fso.source_order_type,
    fso.marketplace_id,
    dm.marketplace_name,
    dm.marketplace_code,
    fso.store_id,
    ds.store_name,
    ds.store_code,
    fso.b2b_partner_id,
    fso.customer_id,
    fso.source_customer_name,
    fso.accurate_customer_no,
    fso.external_order_id,
    fso.external_order_group_id,
    fso.external_invoice_id,
    fso.order_date,
    fso.order_datetime,
    fso.order_status,
    fso.payment_status,
    fso.currency_code,
    COALESCE(fso.gross_order_amount, 0) AS gross_order_amount,
    COALESCE(fso.discount_amount, 0) AS order_discount_amount,
    COALESCE(fso.shipping_fee_amount, 0) AS shipping_fee_amount,
    COALESCE(fso.net_order_amount, 0) AS net_order_amount,
    COALESCE(fso.net_order_amount, 0) AS order_revenue,
    LOWER(COALESCE(fso.order_status, '')) IN (
        'batal', 'canceled', 'cancelled', 'dibatalkan'
    ) AS is_canceled,
    COALESCE(items.item_rows, 0) AS item_rows,
    COALESCE(items.distinct_products, 0) AS distinct_products,
    COALESCE(items.units_sold, 0) AS units_sold,
    COALESCE(items.item_gross_amount, 0) AS item_gross_amount,
    COALESCE(items.item_discount_amount, 0) AS item_discount_amount,
    COALESCE(items.item_net_amount, 0) AS item_net_amount,
    COALESCE(items.item_net_amount, 0) - COALESCE(fso.net_order_amount, 0)
        AS item_to_order_amount_delta,
    fso.source_file,
    fso.source_sheet,
    fso.source_row_number,
    fso.raw_record_id,
    fso.notes
FROM public.vw_sales_order_analytics fso
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = fso.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = fso.store_id
LEFT JOIN item_summary items
    ON items.sales_order_id = fso.sales_order_id;

COMMENT ON VIEW public.vw_sales_order_summary IS
'One row per canonical sales order. order_revenue is sourced exclusively from net_order_amount; item totals are diagnostic.';

CREATE OR REPLACE VIEW public.vw_sales_product_daily AS
SELECT
    fsoi.order_date,
    fsoi.analytics_channel_type,
    fsoi.source_system,
    fsoi.marketplace_id,
    dm.marketplace_name,
    fsoi.store_id,
    ds.store_name,
    fsoi.product_id,
    dp.product_name,
    dp.product_category,
    dp.product_type,
    dp.base_unit,
    dp.net_weight_value,
    dp.net_weight_unit,
    COUNT(DISTINCT fsoi.sales_order_id) AS order_count,
    COUNT(*) AS item_row_count,
    SUM(fsoi.quantity) AS units_sold,
    SUM(fsoi.quantity_returned) AS units_returned_recorded,
    SUM(fsoi.gross_item_amount) AS item_gross_amount,
    SUM(fsoi.discount_amount) AS item_discount_amount,
    SUM(fsoi.net_item_amount) AS item_net_amount
FROM public.vw_sales_order_item_analytics fsoi
LEFT JOIN public.dim_product dp
    ON dp.product_id = fsoi.product_id
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = fsoi.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = fsoi.store_id
GROUP BY
    fsoi.order_date,
    fsoi.analytics_channel_type,
    fsoi.source_system,
    fsoi.marketplace_id,
    dm.marketplace_name,
    fsoi.store_id,
    ds.store_name,
    fsoi.product_id,
    dp.product_name,
    dp.product_category,
    dp.product_type,
    dp.base_unit,
    dp.net_weight_value,
    dp.net_weight_unit;

COMMENT ON VIEW public.vw_sales_product_daily IS
'Daily product performance at channel/source/store/product grain. Monetary columns are item values, not official order revenue.';

CREATE OR REPLACE VIEW public.vw_sales_channel_performance AS
SELECT
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name,
    MIN(order_date) AS first_order_date,
    MAX(order_date) AS last_order_date,
    COUNT(*) AS order_count,
    COUNT(*) FILTER (WHERE is_canceled) AS canceled_order_count,
    COUNT(*) FILTER (WHERE NOT is_canceled) AS non_canceled_order_count,
    SUM(order_revenue) AS revenue,
    SUM(order_revenue) FILTER (WHERE is_canceled) AS canceled_order_value,
    SUM(order_revenue) FILTER (WHERE NOT is_canceled) AS non_canceled_revenue,
    SUM(units_sold) AS units_sold,
    SUM(order_revenue) / NULLIF(COUNT(*), 0) AS average_order_value
FROM public.vw_sales_order_summary
GROUP BY
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name;

COMMENT ON VIEW public.vw_sales_channel_performance IS
'All-time channel/source/store performance using order-header revenue.';

CREATE OR REPLACE VIEW public.vw_sales_customer_performance AS
SELECT
    analytics_channel_type,
    customer_id,
    source_customer_name AS customer_name,
    accurate_customer_no,
    MIN(order_date) AS first_order_date,
    MAX(order_date) AS last_order_date,
    COUNT(*) AS order_count,
    COUNT(*) FILTER (WHERE is_canceled) AS canceled_order_count,
    SUM(order_revenue) AS revenue,
    SUM(order_revenue) FILTER (WHERE NOT is_canceled) AS non_canceled_revenue,
    SUM(units_sold) AS units_sold,
    SUM(order_revenue) / NULLIF(COUNT(*), 0) AS average_order_value,
    COUNT(*) > 1 AS is_repeat_customer
FROM public.vw_sales_order_summary
WHERE analytics_channel_type IN ('offline_b2b', 'offline_retail')
GROUP BY
    analytics_channel_type,
    customer_id,
    source_customer_name,
    accurate_customer_no;

COMMENT ON VIEW public.vw_sales_customer_performance IS
'Offline B2B and retail customer performance using Accurate customer identity and order-header revenue.';

CREATE OR REPLACE VIEW public.vw_sales_trend_daily AS
SELECT
    order_date,
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name,
    COUNT(*) AS order_count,
    COUNT(*) FILTER (WHERE is_canceled) AS canceled_order_count,
    COUNT(*) FILTER (WHERE NOT is_canceled) AS non_canceled_order_count,
    SUM(units_sold) AS units_sold,
    SUM(gross_order_amount) AS gross_order_amount,
    SUM(order_discount_amount) AS order_discount_amount,
    SUM(shipping_fee_amount) AS shipping_fee_amount,
    SUM(order_revenue) AS revenue,
    SUM(order_revenue) FILTER (WHERE is_canceled) AS canceled_order_value,
    SUM(order_revenue) FILTER (WHERE NOT is_canceled) AS non_canceled_revenue,
    SUM(order_revenue) / NULLIF(COUNT(*), 0) AS average_order_value
FROM public.vw_sales_order_summary
GROUP BY
    order_date,
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name;

COMMENT ON VIEW public.vw_sales_trend_daily IS
'Daily sales trend using canonical order-header revenue and per-order item quantities.';

CREATE OR REPLACE VIEW public.vw_sales_trend_monthly AS
SELECT
    DATE_TRUNC('month', order_date)::date AS order_month,
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name,
    SUM(order_count) AS order_count,
    SUM(canceled_order_count) AS canceled_order_count,
    SUM(non_canceled_order_count) AS non_canceled_order_count,
    SUM(units_sold) AS units_sold,
    SUM(gross_order_amount) AS gross_order_amount,
    SUM(order_discount_amount) AS order_discount_amount,
    SUM(shipping_fee_amount) AS shipping_fee_amount,
    SUM(revenue) AS revenue,
    SUM(canceled_order_value) AS canceled_order_value,
    SUM(non_canceled_revenue) AS non_canceled_revenue,
    SUM(revenue) / NULLIF(SUM(order_count), 0) AS average_order_value
FROM public.vw_sales_trend_daily
GROUP BY
    DATE_TRUNC('month', order_date)::date,
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name;

COMMENT ON VIEW public.vw_sales_trend_monthly IS
'Monthly sales trend rolled up from the canonical daily sales trend.';

COMMIT;
