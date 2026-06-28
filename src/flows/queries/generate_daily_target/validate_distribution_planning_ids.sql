SELECT
    warehouse_name,
    store_name,
    product_id,
    warehouse_id,
    sales_channel_id
FROM public.mv_distribution_planning
WHERE warehouse_id IS NULL
   OR sales_channel_id IS NULL
   OR product_id IS NULL
ORDER BY warehouse_name, store_name, product_id;
