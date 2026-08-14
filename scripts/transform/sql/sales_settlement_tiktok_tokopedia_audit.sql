WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_adjustment_id), ''), 'nan'), '-') AS external_order_id,
        LOWER(NULLIF(NULLIF(NULLIF(TRIM(type), ''), 'nan'), '-')) AS transaction_type,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name
    FROM {staging_schema}.tiktok_tokopedia_income
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
resolved_rows AS (
    SELECT
        s.*,
        sl.store_id,
        fso.sales_order_id
    FROM source_rows s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
    LEFT JOIN {target_schema}.fact_sales_order fso
        ON fso.source_system = 'tiktok_tokopedia'
       AND fso.sales_channel_type = 'online'
       AND fso.external_order_id = s.external_order_id
       AND fso.store_id = sl.store_id
    WHERE s.external_order_id IS NOT NULL
      AND COALESCE(s.transaction_type, '') IN ('order', 'pesanan')
),
duplicate_settlements AS (
    SELECT
        external_order_id,
        normalized_store_name,
        COUNT(*) AS row_count
    FROM resolved_rows
    GROUP BY external_order_id, normalized_store_name
    HAVING COUNT(*) > 1
)
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Rows with usable TikTok-Tokopedia order id and type=Order.' AS notes
FROM resolved_rows
UNION ALL
SELECT 'settlement_rows', COUNT(DISTINCT external_order_id || '|' || normalized_store_name)::bigint, 'Distinct TikTok-Tokopedia settlement grain.'
FROM resolved_rows
UNION ALL
SELECT 'unmapped_store_rows', COUNT(*)::bigint, 'Rows whose store_name does not resolve to dim_store.'
FROM resolved_rows
WHERE store_id IS NULL
UNION ALL
SELECT 'unmatched_sales_order_rows', COUNT(*)::bigint, 'Rows whose settlement does not resolve to fact_sales_order.'
FROM resolved_rows
WHERE sales_order_id IS NULL
UNION ALL
SELECT 'duplicate_settlement_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra rows per TikTok-Tokopedia settlement grain.'
FROM duplicate_settlements;
