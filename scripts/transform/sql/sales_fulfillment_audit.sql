WITH source_info AS (
    SELECT source_system
    FROM {staging_schema}.sales_fulfillment_source
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
resolved_rows AS (
    SELECT
        s.*,
        m.marketplace_id,
        sl.store_id
    FROM {staging_schema}.sales_fulfillment_source s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
),
order_lookup AS (
    SELECT DISTINCT ON (
        fso.source_system,
        fso.store_id,
        fso.external_order_id
    )
        fso.source_system,
        fso.store_id,
        fso.external_order_id,
        fso.sales_order_id
    FROM {target_schema}.fact_sales_order fso
    JOIN resolved_rows r
        ON r.source_system = fso.source_system
       AND r.store_id = fso.store_id
       AND r.external_order_id = fso.external_order_id
    WHERE fso.sales_channel_type = 'online'
    ORDER BY fso.source_system, fso.store_id, fso.external_order_id, fso.sales_order_id
),
duplicate_fulfillment_grain AS (
    SELECT
        raw_record_id,
        COUNT(*) AS row_count
    FROM {staging_schema}.sales_fulfillment_source
    GROUP BY raw_record_id
    HAVING COUNT(*) > 1
)
SELECT 'source_fulfillment_rows' AS metric, COUNT(*)::bigint AS value, 'Order file rows carrying fulfillment/logistics fields.' AS notes
FROM {staging_schema}.sales_fulfillment_source
UNION ALL
SELECT 'fulfillment_rows', COUNT(DISTINCT raw_record_id)::bigint, 'Distinct fulfillment grain before insert.'
FROM {staging_schema}.sales_fulfillment_source
UNION ALL
SELECT 'unmapped_store_rows', COUNT(*)::bigint, 'Rows whose store_name does not resolve to dim_store.'
FROM resolved_rows
WHERE store_id IS NULL
UNION ALL
SELECT 'unmatched_sales_order_rows', COUNT(*)::bigint, 'Rows whose fulfillment does not resolve to fact_sales_order.'
FROM resolved_rows r
LEFT JOIN order_lookup ol
    ON ol.source_system = r.source_system
   AND ol.store_id = r.store_id
   AND ol.external_order_id = r.external_order_id
WHERE r.store_id IS NOT NULL
  AND ol.sales_order_id IS NULL
UNION ALL
SELECT 'rows_with_tracking_number', COUNT(*)::bigint, 'Rows with tracking number/resi populated.'
FROM {staging_schema}.sales_fulfillment_source
WHERE tracking_number IS NOT NULL
UNION ALL
SELECT 'rows_with_package_id', COUNT(*)::bigint, 'Rows with marketplace package id populated.'
FROM {staging_schema}.sales_fulfillment_source
WHERE external_package_id IS NOT NULL
UNION ALL
SELECT 'rows_with_warehouse_name', COUNT(*)::bigint, 'Rows with source warehouse name populated.'
FROM {staging_schema}.sales_fulfillment_source
WHERE source_warehouse_name IS NOT NULL
UNION ALL
SELECT 'rows_with_shipping_provider', COUNT(*)::bigint, 'Rows with source shipping provider/service populated.'
FROM {staging_schema}.sales_fulfillment_source
WHERE source_shipping_provider IS NOT NULL
   OR source_shipping_service IS NOT NULL
UNION ALL
SELECT 'rows_with_delivered_at', COUNT(*)::bigint, 'Rows with delivered timestamp populated.'
FROM {staging_schema}.sales_fulfillment_source
WHERE delivered_at_text IS NOT NULL
UNION ALL
SELECT 'duplicate_fulfillment_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra temp rows with the same fulfillment raw_record_id.'
FROM duplicate_fulfillment_grain;
