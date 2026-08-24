WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(no_pesanan), ''), 'nan'), '-') AS external_order_id,
        TRIM(store_name) AS store_name,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(waktu_pesanan_dibuat), ''), 'nan'), '-') AS order_created_at_text,
        NULLIF(NULLIF(NULLIF(TRIM(tanggal_dana_dilepaskan), ''), 'nan'), '-') AS released_at_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_penghasilan), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS settlement_amount_text,
        source_filename
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
)
SELECT
    store_name,
    normalized_store_name,
    external_order_id,
    order_created_at_text,
    released_at_text,
    settlement_amount_text,
    source_filename
FROM resolved_rows
WHERE sales_order_id IS NULL
ORDER BY normalized_store_name, released_at_text, external_order_id, source_filename;
