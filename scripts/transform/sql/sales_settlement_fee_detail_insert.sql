WITH source_fee AS (
    SELECT *
    FROM {staging_schema}.sales_settlement_fee_source
    WHERE fee_source_sequence >= :batch_start
      AND fee_source_sequence < :batch_end
),
source_info AS (
    SELECT source_system
    FROM source_fee
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
    FROM source_fee s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
),
match_grain AS (
    SELECT DISTINCT
        source_system,
        store_id,
        external_order_id,
        CASE
            WHEN source_system = 'lazada' THEN COALESCE(external_order_item_id, '')
            ELSE ''
        END AS match_external_order_item_id,
        CASE
            WHEN source_system = 'lazada' THEN COALESCE(source_sku_code, '')
            ELSE ''
        END AS match_source_sku_code
    FROM resolved_rows
    WHERE store_id IS NOT NULL
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
        fss.sales_settlement_id,
        fss.sales_order_id
    FROM {target_schema}.fact_sales_settlement fss
    JOIN match_grain mg
        ON mg.source_system = fss.source_system
       AND mg.store_id = fss.store_id
       AND mg.external_order_id = fss.external_order_id
       AND mg.match_external_order_item_id = CASE
            WHEN fss.source_system = 'lazada' THEN COALESCE(fss.external_order_item_id, '')
            ELSE ''
        END
       AND mg.match_source_sku_code = CASE
            WHEN fss.source_system = 'lazada' THEN COALESCE(fss.source_sku_code, '')
            ELSE ''
        END
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
        r.*,
        fss.sales_settlement_id,
        fss.sales_order_id
    FROM resolved_rows r
    LEFT JOIN settlement_lookup fss
        ON fss.source_system = r.source_system
       AND fss.store_id = r.store_id
       AND fss.external_order_id = r.external_order_id
       AND fss.match_external_order_item_id = CASE
            WHEN r.source_system = 'lazada' THEN COALESCE(r.external_order_item_id, '')
            ELSE ''
       END
       AND fss.match_source_sku_code = CASE
            WHEN r.source_system = 'lazada' THEN COALESCE(r.source_sku_code, '')
            ELSE ''
       END
)
INSERT INTO {target_schema}.fact_sales_settlement_fee_detail (
    source_system,
    sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    sales_settlement_id,
    fee_type_id,
    external_order_id,
    external_order_item_id,
    source_sku_code,
    fee_grain_type,
    raw_fee_name,
    raw_fee_amount,
    signed_fee_amount,
    amount_sign_from_source,
    sign_rule,
    sign_confidence,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    notes
)
SELECT
    source_system,
    'online' AS sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    sales_settlement_id,
    fee_type_id,
    external_order_id,
    external_order_item_id,
    source_sku_code,
    fee_grain_type,
    raw_fee_name,
    raw_fee_amount::numeric,
    signed_fee_amount::numeric,
    amount_sign_from_source,
    sign_rule,
    sign_confidence,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    CONCAT_WS(
        '; ',
        'Loaded by scripts/transform/sales_fee_detail_phase_3.py',
        'source_table=' || source_table,
        'review_status=' || review_status
    ) AS notes
FROM settlement_matches
WHERE store_id IS NOT NULL
  AND sales_settlement_id IS NOT NULL
ON CONFLICT DO NOTHING;
