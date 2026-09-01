WITH source_info AS (
    SELECT source_system
    FROM {staging_schema}.sales_settlement_fee_source
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
fee_match_grain AS (
    SELECT
        s.source_system,
        s.normalized_store_name,
        s.external_order_id,
        CASE
            WHEN s.source_system = 'lazada' THEN COALESCE(s.external_order_item_id, '')
            ELSE ''
        END AS match_external_order_item_id,
        CASE
            WHEN s.source_system = 'lazada' THEN COALESCE(s.source_sku_code, '')
            ELSE ''
        END AS match_source_sku_code,
        COUNT(*) AS fee_row_count
    FROM {staging_schema}.sales_settlement_fee_source s
    GROUP BY
        s.source_system,
        s.normalized_store_name,
        s.external_order_id,
        CASE
            WHEN s.source_system = 'lazada' THEN COALESCE(s.external_order_item_id, '')
            ELSE ''
        END,
        CASE
            WHEN s.source_system = 'lazada' THEN COALESCE(s.source_sku_code, '')
            ELSE ''
        END
),
resolved_grain AS (
    SELECT
        fg.*,
        sl.store_id
    FROM fee_match_grain fg
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = fg.normalized_store_name
),
settlement_lookup AS (
    SELECT DISTINCT ON (
        fss.source_system,
        fss.store_id,
        fss.external_order_id,
        CASE
            WHEN fss.source_system = 'lazada' THEN COALESCE(fss.external_order_item_id, '')
            ELSE ''
        END,
        CASE
            WHEN fss.source_system = 'lazada' THEN COALESCE(fss.source_sku_code, '')
            ELSE ''
        END
    )
        fss.source_system,
        fss.store_id,
        fss.external_order_id,
        CASE
            WHEN fss.source_system = 'lazada' THEN COALESCE(fss.external_order_item_id, '')
            ELSE ''
        END AS match_external_order_item_id,
        CASE
            WHEN fss.source_system = 'lazada' THEN COALESCE(fss.source_sku_code, '')
            ELSE ''
        END AS match_source_sku_code,
        fss.sales_settlement_id
    FROM {target_schema}.fact_sales_settlement fss
    JOIN source_info si
        ON si.source_system = fss.source_system
    WHERE fss.sales_channel_type = 'online'
    ORDER BY
        fss.source_system,
        fss.store_id,
        fss.external_order_id,
        CASE
            WHEN fss.source_system = 'lazada' THEN COALESCE(fss.external_order_item_id, '')
            ELSE ''
        END,
        CASE
            WHEN fss.source_system = 'lazada' THEN COALESCE(fss.source_sku_code, '')
            ELSE ''
        END,
        fss.sales_settlement_id
),
settlement_matches AS (
    SELECT
        rg.*,
        fss.sales_settlement_id
    FROM resolved_grain rg
    LEFT JOIN settlement_lookup fss
        ON fss.source_system = rg.source_system
       AND fss.store_id = rg.store_id
       AND fss.external_order_id = rg.external_order_id
       AND fss.match_external_order_item_id = rg.match_external_order_item_id
       AND fss.match_source_sku_code = rg.match_source_sku_code
),
duplicate_fee_grain AS (
    SELECT
        raw_record_id,
        COUNT(*) AS row_count
    FROM {staging_schema}.sales_settlement_fee_source
    GROUP BY raw_record_id
    HAVING COUNT(*) > 1
)
SELECT 'source_fee_rows' AS metric, COUNT(*)::bigint AS value, 'Non-zero fee rows extracted from income files.' AS notes
FROM {staging_schema}.sales_settlement_fee_source
UNION ALL
SELECT 'distinct_fee_rows', COUNT(DISTINCT raw_record_id)::bigint, 'Distinct source fee grain before insert.'
FROM {staging_schema}.sales_settlement_fee_source
UNION ALL
SELECT 'unmapped_store_rows', COALESCE(SUM(fee_row_count), 0)::bigint, 'Rows whose store_name does not resolve to dim_store.'
FROM settlement_matches
WHERE store_id IS NULL
UNION ALL
SELECT 'unmatched_settlement_rows', COALESCE(SUM(fee_row_count), 0)::bigint, 'Rows whose fee detail does not resolve to fact_sales_settlement.'
FROM settlement_matches
WHERE sales_settlement_id IS NULL
UNION ALL
SELECT 'review_fee_rows', COUNT(*)::bigint, 'Rows whose fee type still has low sign confidence.'
FROM {staging_schema}.sales_settlement_fee_source
WHERE sign_confidence = 'low'
UNION ALL
SELECT 'duplicate_fee_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra temp rows with the same raw_record_id.'
FROM duplicate_fee_grain;
