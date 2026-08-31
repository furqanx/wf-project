WITH marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE marketplace_code = (
        SELECT source_system
        FROM {staging_schema}.sales_settlement_fee_source
        LIMIT 1
    )
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
    FROM {staging_schema}.sales_settlement_fee_source s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
),
settlement_matches AS (
    SELECT
        r.*,
        fss.sales_settlement_id,
        fss.sales_order_id
    FROM resolved_rows r
    LEFT JOIN LATERAL (
        SELECT fss.sales_settlement_id, fss.sales_order_id
        FROM {target_schema}.fact_sales_settlement fss
        WHERE fss.source_system = r.source_system
          AND fss.sales_channel_type = 'online'
          AND fss.store_id = r.store_id
          AND (
              (
                  r.source_system = 'lazada'
                  AND fss.external_order_id = r.external_order_id
                  AND COALESCE(fss.external_order_item_id, '') = COALESCE(r.external_order_item_id, '')
                  AND COALESCE(fss.source_sku_code, '') = COALESCE(r.source_sku_code, '')
              )
              OR (
                  r.source_system IN ('shopee', 'tiktok_tokopedia')
                  AND fss.external_order_id = r.external_order_id
              )
          )
        ORDER BY fss.sales_settlement_id
        LIMIT 1
    ) fss ON TRUE
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
