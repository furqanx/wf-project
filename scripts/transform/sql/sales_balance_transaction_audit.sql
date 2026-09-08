WITH source_info AS (
    SELECT source_system
    FROM {staging_schema}.sales_balance_transaction_source
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
    FROM {staging_schema}.sales_balance_transaction_source s
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
        ON r.external_order_id IS NOT NULL
       AND r.source_system = fso.source_system
       AND r.store_id = fso.store_id
       AND r.external_order_id = fso.external_order_id
    WHERE fso.sales_channel_type = 'online'
    ORDER BY fso.source_system, fso.store_id, fso.external_order_id, fso.sales_order_id
),
settlement_lookup AS (
    SELECT DISTINCT ON (
        fss.source_system,
        fss.store_id,
        fss.external_order_id
    )
        fss.source_system,
        fss.store_id,
        fss.external_order_id,
        fss.sales_settlement_id
    FROM {target_schema}.fact_sales_settlement fss
    JOIN resolved_rows r
        ON r.external_order_id IS NOT NULL
       AND r.source_system = fss.source_system
       AND r.store_id = fss.store_id
       AND r.external_order_id = fss.external_order_id
    WHERE fss.sales_channel_type = 'online'
    ORDER BY fss.source_system, fss.store_id, fss.external_order_id, fss.sales_settlement_id
),
duplicate_balance_grain AS (
    SELECT
        raw_record_id,
        COUNT(*) AS row_count
    FROM {staging_schema}.sales_balance_transaction_source
    GROUP BY raw_record_id
    HAVING COUNT(*) > 1
)
SELECT 'source_balance_rows' AS metric, COUNT(*)::bigint AS value, 'Report rows with usable amount extracted from marketplace report files.' AS notes
FROM {staging_schema}.sales_balance_transaction_source
UNION ALL
SELECT 'distinct_balance_rows', COUNT(DISTINCT raw_record_id)::bigint, 'Distinct source balance grain before insert.'
FROM {staging_schema}.sales_balance_transaction_source
UNION ALL
SELECT 'unmapped_store_rows', COUNT(*)::bigint, 'Rows whose store_name does not resolve to dim_store.'
FROM resolved_rows
WHERE store_id IS NULL
UNION ALL
SELECT 'rows_with_external_order_id', COUNT(*)::bigint, 'Rows carrying marketplace order id in report data.'
FROM {staging_schema}.sales_balance_transaction_source
WHERE external_order_id IS NOT NULL
UNION ALL
SELECT 'matched_sales_order_rows', COUNT(*)::bigint, 'Rows that can resolve to fact_sales_order by source/store/order id.'
FROM resolved_rows r
JOIN order_lookup ol
    ON ol.source_system = r.source_system
   AND ol.store_id = r.store_id
   AND ol.external_order_id = r.external_order_id
UNION ALL
SELECT 'matched_sales_settlement_rows', COUNT(*)::bigint, 'Rows that can resolve to fact_sales_settlement by source/store/order id.'
FROM resolved_rows r
JOIN settlement_lookup sl
    ON sl.source_system = r.source_system
   AND sl.store_id = r.store_id
   AND sl.external_order_id = r.external_order_id
UNION ALL
SELECT 'zero_amount_rows', COUNT(*)::bigint, 'Rows with amount = 0; retained as ledger events.'
FROM {staging_schema}.sales_balance_transaction_source
WHERE raw_amount::numeric = 0
UNION ALL
SELECT 'duplicate_balance_grain_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra temp rows with the same raw_record_id.'
FROM duplicate_balance_grain;
