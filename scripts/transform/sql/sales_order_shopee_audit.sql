WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(no_pesanan), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        COALESCE(
            NULLIF(NULLIF(NULLIF(TRIM(nomor_referensi_sku), ''), 'nan'), '-'),
            NULLIF(NULLIF(NULLIF(TRIM(sku_induk), ''), 'nan'), '-')
        ) AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(nama_produk), ''), 'nan'), '-') AS source_product_name,
        NULLIF(NULLIF(NULLIF(TRIM(nama_variasi), ''), 'nan'), '-') AS source_variation_name,
        source_filename
    FROM {staging_schema}.shopee_orders
),
marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE LOWER(marketplace_name) = 'shopee'
    LIMIT 1
),
resolved_rows AS (
    SELECT
        s.*,
        ds.store_id,
        COALESCE(pma.product_id, psa.product_id) AS product_id,
        COALESCE(pma.product_sku_alias_id, psa.product_sku_alias_id) AS product_sku_alias_id
    FROM source_rows s
    CROSS JOIN marketplace m
    LEFT JOIN {target_schema}.dim_store ds
        ON ds.marketplace_id = m.marketplace_id
       AND (
            LOWER(REGEXP_REPLACE(ds.store_name, '[^a-zA-Z0-9]+', '_', 'g')) = s.normalized_store_name
            OR LOWER(ds.store_code) = s.normalized_store_name
       )
    LEFT JOIN {target_schema}.product_marketplace_alias pma
        ON pma.marketplace_code = 'shopee'
       AND pma.is_active
       AND (
            LOWER(pma.raw_alias) = LOWER(s.source_sku_code)
            OR LOWER(pma.source_sku_code) = LOWER(s.source_sku_code)
            OR LOWER(pma.normalized_alias) = LOWER(s.source_sku_code)
       )
    LEFT JOIN {target_schema}.product_sku_alias psa
        ON psa.sku_code = s.source_sku_code
       AND psa.is_active
    WHERE s.external_order_id IS NOT NULL
),
duplicate_orders AS (
    SELECT
        external_order_id,
        normalized_store_name,
        COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY external_order_id, normalized_store_name
    HAVING COUNT(*) > 1
),
duplicate_items AS (
    SELECT
        external_order_id,
        normalized_store_name,
        COALESCE(source_sku_code, ''),
        COALESCE(source_product_name, ''),
        COALESCE(source_variation_name, ''),
        COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY
        external_order_id,
        normalized_store_name,
        COALESCE(source_sku_code, ''),
        COALESCE(source_product_name, ''),
        COALESCE(source_variation_name, '')
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Rows with usable order id from public_staging.shopee_orders.' AS notes
FROM resolved_rows
UNION ALL
SELECT 'source_orders', COUNT(DISTINCT external_order_id || '|' || normalized_store_name)::bigint, 'Distinct source order grain.'
FROM resolved_rows
UNION ALL
SELECT 'unmapped_store_rows', COUNT(*)::bigint, 'Rows whose store_name does not resolve to dim_store.'
FROM resolved_rows
WHERE store_id IS NULL
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Rows whose SKU/alias does not resolve to product master.'
FROM resolved_rows
WHERE product_id IS NULL
UNION ALL
SELECT 'duplicate_source_order_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra source rows per order grain. Usually expected because one order has multiple items.'
FROM duplicate_orders
UNION ALL
SELECT 'duplicate_source_item_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Potential duplicated item lines by source order/store/SKU/product/variation.'
FROM duplicate_items;
