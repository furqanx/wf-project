WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(no_pesanan), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name
    FROM {staging_schema}.shopee_income_main
),
marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE marketplace_code = 'shopee'
    LIMIT 1
),
resolved_rows AS (
    SELECT
        s.*,
        COALESCE(ds.store_id, alias_store.store_id) AS store_id,
        fso.sales_order_id
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
    LEFT JOIN {target_schema}.fact_sales_order fso
        ON fso.source_system = 'shopee'
       AND fso.sales_channel_type = 'online'
       AND fso.external_order_id = s.external_order_id
       AND fso.store_id = COALESCE(ds.store_id, alias_store.store_id)
    WHERE s.external_order_id IS NOT NULL
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
SELECT 'source_rows' AS metric, COUNT(*)::bigint AS value, 'Rows with usable Shopee order id from income main.' AS notes
FROM resolved_rows
UNION ALL
SELECT 'settlement_rows', COUNT(DISTINCT external_order_id || '|' || normalized_store_name)::bigint, 'Distinct Shopee settlement grain.'
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
SELECT 'duplicate_settlement_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra rows per Shopee settlement grain.'
FROM duplicate_settlements;
