-- Post-deployment checks for create_sales_analytics_channel_views.sql.

SELECT
    analytics_channel_type,
    source_system,
    COUNT(*) AS order_rows,
    SUM(net_order_amount) AS net_order_amount
FROM public.vw_sales_order_analytics
GROUP BY analytics_channel_type, source_system
ORDER BY analytics_channel_type, source_system;

SELECT
    analytics_exclusion_reason,
    source_system,
    COUNT(*) AS excluded_rows,
    SUM(net_order_amount) AS excluded_net_order_amount
FROM public.vw_sales_order_channel_classification
WHERE is_analytics_included = FALSE
GROUP BY analytics_exclusion_reason, source_system
ORDER BY analytics_exclusion_reason, source_system;

SELECT
    COUNT(*) FILTER (
        WHERE source_system = 'accurate'
          AND analytics_channel_type = 'online'
    ) AS accurate_online_rows_included,
    COUNT(*) FILTER (
        WHERE source_system = 'accurate'
          AND analytics_channel_type IN ('offline_b2b', 'offline_retail')
    ) AS accurate_offline_rows_included,
    COUNT(*) FILTER (
        WHERE analytics_exclusion_reason = 'duplicate_marketplace_record'
    ) AS marketplace_duplicate_rows_excluded
FROM public.vw_sales_order_channel_classification;

SELECT
    source_system,
    external_order_id,
    store_id,
    order_status,
    net_order_amount,
    product_quantity_signature,
    is_analytics_included,
    analytics_exclusion_reason
FROM public.vw_sales_order_channel_classification
WHERE source_system = 'lazada'
  AND external_order_id = '1448141276500771'
ORDER BY sales_order_id;

SELECT
    COUNT(*) AS included_lazada_reused_id_rows
FROM public.vw_sales_order_analytics
WHERE source_system = 'lazada'
  AND external_order_id = '1448141276500771';
