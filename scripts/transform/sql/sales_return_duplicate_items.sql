SELECT
    source_system,
    return_item_raw_record_id,
    COUNT(*) AS row_count,
    COUNT(DISTINCT external_order_id) AS order_count,
    STRING_AGG(DISTINCT store_name, ' | ' ORDER BY store_name) AS store_names,
    STRING_AGG(DISTINCT source_sku_code, ' | ' ORDER BY source_sku_code) AS source_sku_codes,
    STRING_AGG(DISTINCT source_product_name, ' | ' ORDER BY source_product_name) AS source_product_names,
    STRING_AGG(DISTINCT source_file, ' | ' ORDER BY source_file) AS source_files
FROM {staging_schema}.sales_return_source
GROUP BY source_system, return_item_raw_record_id
HAVING COUNT(*) > 1
ORDER BY row_count DESC, source_system, return_item_raw_record_id
LIMIT 1000;
