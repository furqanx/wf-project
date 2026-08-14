WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_id), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(sku_id), ''), 'nan'), '-') AS sku_id,
        COALESCE(
            NULLIF(NULLIF(NULLIF(TRIM(seller_sku), ''), 'nan'), '-'),
            NULLIF(NULLIF(NULLIF(TRIM(sku_id), ''), 'nan'), '-')
        ) AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(product_name), ''), 'nan'), '-') AS source_product_name,
        NULLIF(NULLIF(NULLIF(TRIM(variation), ''), 'nan'), '-') AS source_variation_name,
        NULLIF(NULLIF(NULLIF(TRIM(tokopedia_invoice_number), ''), 'nan'), '-') AS external_invoice_id,
        source_filename
    FROM {staging_schema}.tiktok_tokopedia_orders
),
marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE marketplace_code = 'tiktok_tokopedia'
    LIMIT 1
),
store_lookup AS (
    SELECT DISTINCT ON (lookup_store_name)
        lookup_store_name,
        store_id
    FROM (
        SELECT
            LOWER(REGEXP_REPLACE(ds.store_name, '[^a-zA-Z0-9]+', '_', 'g')) AS lookup_store_name,
            ds.store_id,
            1 AS priority
        FROM {target_schema}.dim_store ds
        JOIN marketplace m
            ON m.marketplace_id = ds.marketplace_id
        UNION ALL
        SELECT
            LOWER(ds.store_code) AS lookup_store_name,
            ds.store_id,
            2 AS priority
        FROM {target_schema}.dim_store ds
        JOIN marketplace m
            ON m.marketplace_id = ds.marketplace_id
        WHERE ds.store_code IS NOT NULL
        UNION ALL
        SELECT
            sna.normalized_store_name AS lookup_store_name,
            sna.store_id,
            3 AS priority
        FROM {target_schema}.store_name_alias sna
        JOIN {target_schema}.dim_store ds
            ON ds.store_id = sna.store_id
        JOIN marketplace m
            ON m.marketplace_id = ds.marketplace_id
    ) lookup
    WHERE lookup_store_name IS NOT NULL
    ORDER BY lookup_store_name, priority, store_id
),
marketplace_alias_lookup AS (
    SELECT DISTINCT ON (alias_code)
        alias_code,
        product_id,
        product_sku_alias_id
    FROM (
        SELECT LOWER(raw_alias) AS alias_code, product_id, product_sku_alias_id, product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE marketplace_code IN ('tiktok_tokopedia', 'tiktok')
          AND is_active
        UNION ALL
        SELECT LOWER(source_sku_code) AS alias_code, product_id, product_sku_alias_id, product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE marketplace_code IN ('tiktok_tokopedia', 'tiktok')
          AND is_active
        UNION ALL
        SELECT LOWER(mapped_source_sku_code) AS alias_code, product_id, product_sku_alias_id, product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE marketplace_code IN ('tiktok_tokopedia', 'tiktok')
          AND is_active
        UNION ALL
        SELECT LOWER(normalized_alias) AS alias_code, product_id, product_sku_alias_id, product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE marketplace_code IN ('tiktok_tokopedia', 'tiktok')
          AND is_active
    ) aliases
    WHERE alias_code IS NOT NULL
    ORDER BY alias_code, product_marketplace_alias_id
),
sku_alias_lookup AS (
    SELECT DISTINCT ON (LOWER(sku_code))
        LOWER(sku_code) AS sku_code,
        product_id,
        product_sku_alias_id
    FROM {target_schema}.product_sku_alias
    WHERE is_active
    ORDER BY LOWER(sku_code), product_sku_alias_id
),
resolved_rows AS (
    SELECT
        s.*,
        sl.store_id,
        COALESCE(pma.product_id, psa.product_id) AS product_id,
        COALESCE(pma.product_sku_alias_id, psa.product_sku_alias_id) AS product_sku_alias_id
    FROM source_rows s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
    LEFT JOIN marketplace_alias_lookup pma
        ON pma.alias_code = LOWER(s.source_sku_code)
    LEFT JOIN sku_alias_lookup psa
        ON psa.sku_code = LOWER(s.source_sku_code)
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
        COALESCE(sku_id, ''),
        COALESCE(source_sku_code, ''),
        COALESCE(source_product_name, ''),
        COALESCE(source_variation_name, ''),
        COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY
        external_order_id,
        normalized_store_name,
        COALESCE(sku_id, ''),
        COALESCE(source_sku_code, ''),
        COALESCE(source_product_name, ''),
        COALESCE(source_variation_name, '')
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Rows with usable order id from staging folder temp table.' AS notes
FROM resolved_rows
UNION ALL
SELECT 'source_orders', COUNT(DISTINCT external_order_id || '|' || normalized_store_name)::bigint, 'Distinct source order grain.'
FROM resolved_rows
UNION ALL
SELECT 'unmapped_store_rows', COUNT(*)::bigint, 'Rows whose store_name does not resolve to dim_store.'
FROM resolved_rows
WHERE store_id IS NULL
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Rows whose seller_sku does not resolve to product SKU alias.'
FROM resolved_rows
WHERE product_sku_alias_id IS NULL
UNION ALL
SELECT 'duplicate_source_order_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra source rows per order grain. Usually expected because one order has multiple items.'
FROM duplicate_orders
UNION ALL
SELECT 'duplicate_source_item_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Potential duplicated TikTok-Tokopedia item lines by source order/store/SKU/product/variation.'
FROM duplicate_items;
