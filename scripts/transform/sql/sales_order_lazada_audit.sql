WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_number), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        COALESCE(
            NULLIF(NULLIF(NULLIF(TRIM(seller_sku), ''), 'nan'), '-'),
            NULLIF(NULLIF(NULLIF(TRIM(lazada_sku), ''), 'nan'), '-')
        ) AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(item_name), ''), 'nan'), '-') AS source_product_name,
        NULLIF(NULLIF(NULLIF(TRIM(variation), ''), 'nan'), '-') AS source_variation_name,
        NULLIF(NULLIF(NULLIF(TRIM(order_item_id), ''), 'nan'), '-') AS source_line_id,
        source_filename
    FROM {staging_schema}.lazada_orders
),
marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE marketplace_code = 'lazada'
    LIMIT 1
),
resolved_rows AS (
    SELECT
        s.*,
        COALESCE(ds.store_id, alias_store.store_id) AS store_id,
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
    LEFT JOIN {target_schema}.store_name_alias sna
        ON sna.normalized_store_name = s.normalized_store_name
    LEFT JOIN {target_schema}.dim_store alias_store
        ON alias_store.store_id = sna.store_id
       AND alias_store.marketplace_id = m.marketplace_id
    LEFT JOIN {target_schema}.product_marketplace_alias pma
        ON pma.marketplace_code = 'lazada'
       AND pma.is_active
       AND (
            LOWER(pma.raw_alias) = LOWER(s.source_sku_code)
            OR LOWER(pma.source_sku_code) = LOWER(s.source_sku_code)
            OR LOWER(pma.mapped_source_sku_code) = LOWER(s.source_sku_code)
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
        COALESCE(source_line_id, ''),
        COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY
        external_order_id,
        normalized_store_name,
        COALESCE(source_line_id, '')
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Rows with usable order id from public_staging.lazada_orders.' AS notes
FROM resolved_rows
UNION ALL
SELECT 'source_orders', COUNT(DISTINCT external_order_id || '|' || normalized_store_name)::bigint, 'Distinct source order grain.'
FROM resolved_rows
UNION ALL
SELECT 'unmapped_store_rows', COUNT(*)::bigint, 'Rows whose store_name does not resolve to dim_store.'
FROM resolved_rows
WHERE store_id IS NULL
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Rows whose seller_sku/lazada_sku does not resolve to product SKU alias.'
FROM resolved_rows
WHERE product_sku_alias_id IS NULL
UNION ALL
SELECT 'duplicate_source_order_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra source rows per order grain. Usually expected because one order has multiple items.'
FROM duplicate_orders
UNION ALL
SELECT 'duplicate_source_item_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Potential duplicated Lazada order item lines by source order/store/order_item_id.'
FROM duplicate_items;
