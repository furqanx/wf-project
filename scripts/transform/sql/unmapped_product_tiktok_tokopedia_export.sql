WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_id), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        store_name,
        NULLIF(NULLIF(NULLIF(TRIM(sku_id), ''), 'nan'), '-') AS sku_id,
        COALESCE(
            NULLIF(NULLIF(NULLIF(TRIM(seller_sku), ''), 'nan'), '-'),
            NULLIF(NULLIF(NULLIF(TRIM(sku_id), ''), 'nan'), '-')
        ) AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(product_name), ''), 'nan'), '-') AS source_product_name,
        NULLIF(NULLIF(NULLIF(TRIM(variation), ''), 'nan'), '-') AS source_variation_name,
        source_filename
    FROM {staging_schema}.tiktok_tokopedia_orders
),
resolved_rows AS (
    SELECT
        s.*,
        COALESCE(pma.product_sku_alias_id, psa.product_sku_alias_id) AS product_sku_alias_id
    FROM source_rows s
    LEFT JOIN LATERAL (
        SELECT pma.product_sku_alias_id
        FROM {target_schema}.product_marketplace_alias pma
        WHERE pma.marketplace_code IN ('tiktok_tokopedia', 'tiktok')
          AND pma.is_active
          AND (
            LOWER(pma.raw_alias) = LOWER(s.source_sku_code)
            OR LOWER(pma.source_sku_code) = LOWER(s.source_sku_code)
            OR LOWER(pma.mapped_source_sku_code) = LOWER(s.source_sku_code)
            OR LOWER(pma.normalized_alias) = LOWER(s.source_sku_code)
          )
        ORDER BY pma.product_marketplace_alias_id
        LIMIT 1
    ) pma ON TRUE
    LEFT JOIN LATERAL (
        SELECT psa.product_sku_alias_id
        FROM {target_schema}.product_sku_alias psa
        WHERE psa.sku_code = s.source_sku_code
          AND psa.is_active
        ORDER BY psa.product_sku_alias_id
        LIMIT 1
    ) psa ON TRUE
    WHERE s.external_order_id IS NOT NULL
)
SELECT
    source_sku_code,
    sku_id,
    COUNT(*) AS row_count,
    COUNT(DISTINCT external_order_id || '|' || normalized_store_name) AS order_count,
    STRING_AGG(DISTINCT store_name, ' | ' ORDER BY store_name) AS stores,
    STRING_AGG(DISTINCT source_product_name, ' | ' ORDER BY source_product_name) AS sample_product_names,
    STRING_AGG(DISTINCT source_variation_name, ' | ' ORDER BY source_variation_name) AS sample_variations,
    STRING_AGG(DISTINCT source_filename, ' | ' ORDER BY source_filename) AS sample_source_files
FROM resolved_rows
WHERE product_sku_alias_id IS NULL
GROUP BY source_sku_code, sku_id
ORDER BY row_count DESC, source_sku_code
LIMIT 300;
