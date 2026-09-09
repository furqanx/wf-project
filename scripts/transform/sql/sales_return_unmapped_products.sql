WITH source_info AS (
    SELECT source_system
    FROM {staging_schema}.sales_return_source
    LIMIT 1
),
marketplace AS (
    SELECT dm.marketplace_id
    FROM {target_schema}.dim_marketplace dm
    JOIN source_info si
        ON si.source_system = dm.marketplace_code
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
    SELECT DISTINCT ON (source_system, alias_code)
        source_system,
        alias_code,
        product_id,
        product_sku_alias_id
    FROM (
        SELECT
            CASE WHEN marketplace_code = 'tiktok' THEN 'tiktok_tokopedia' ELSE marketplace_code END AS source_system,
            LOWER(raw_alias) AS alias_code,
            product_id,
            product_sku_alias_id,
            product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE is_active
        UNION ALL
        SELECT
            CASE WHEN marketplace_code = 'tiktok' THEN 'tiktok_tokopedia' ELSE marketplace_code END AS source_system,
            LOWER(source_sku_code) AS alias_code,
            product_id,
            product_sku_alias_id,
            product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE is_active
        UNION ALL
        SELECT
            CASE WHEN marketplace_code = 'tiktok' THEN 'tiktok_tokopedia' ELSE marketplace_code END AS source_system,
            LOWER(mapped_source_sku_code) AS alias_code,
            product_id,
            product_sku_alias_id,
            product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE is_active
        UNION ALL
        SELECT
            CASE WHEN marketplace_code = 'tiktok' THEN 'tiktok_tokopedia' ELSE marketplace_code END AS source_system,
            LOWER(normalized_alias) AS alias_code,
            product_id,
            product_sku_alias_id,
            product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE is_active
    ) aliases
    WHERE alias_code IS NOT NULL
    ORDER BY source_system, alias_code, product_marketplace_alias_id
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
    FROM {staging_schema}.sales_return_source s
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
    LEFT JOIN marketplace_alias_lookup pma
        ON pma.source_system = s.source_system
       AND pma.alias_code = LOWER(s.source_sku_code)
    LEFT JOIN sku_alias_lookup psa
        ON psa.sku_code = LOWER(s.source_sku_code)
)
SELECT
    source_system,
    store_name,
    source_sku_code,
    source_product_name,
    source_variation_name,
    return_type,
    return_status,
    COUNT(*) AS row_count,
    COUNT(DISTINCT external_order_id) AS order_count,
    STRING_AGG(DISTINCT source_file, ' | ' ORDER BY source_file) AS source_files
FROM resolved_rows
WHERE store_id IS NOT NULL
  AND product_sku_alias_id IS NULL
GROUP BY
    source_system,
    store_name,
    source_sku_code,
    source_product_name,
    source_variation_name,
    return_type,
    return_status
ORDER BY row_count DESC, source_sku_code, source_product_name
LIMIT 1000;
