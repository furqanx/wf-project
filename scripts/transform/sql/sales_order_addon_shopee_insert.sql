WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(no_pesanan), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        COALESCE(
            NULLIF(NULLIF(NULLIF(TRIM(nomor_referensi_sku), ''), 'nan'), '-'),
            NULLIF(NULLIF(NULLIF(TRIM(sku_induk), ''), 'nan'), '-')
        ) AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(nama_produk), ''), 'nan'), '-') AS source_addon_name,
        NULLIF(NULLIF(NULLIF(TRIM(nama_variasi), ''), 'nan'), '-') AS source_variation_name,
        NULLIF(NULLIF(NULLIF(TRIM(status_pesanan), ''), 'nan'), '-') AS addon_status,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(jumlah), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS quantity_text,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(harga_awal), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS unit_price_text,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(total_diskon), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS discount_text,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(total_harga_produk), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS net_addon_text,
        source_filename
    FROM {staging_schema}.shopee_orders
),
source_rows AS (
    SELECT
        external_order_id,
        normalized_store_name,
        source_sku_code,
        source_addon_name,
        source_variation_name,
        addon_status,
        CASE
            WHEN quantity_text ~ '^-?[0-9]+$'
                THEN quantity_text::numeric
            ELSE NULL
        END AS quantity,
        CASE
            WHEN unit_price_text ~ '^-?[0-9]+$'
                THEN unit_price_text::numeric
            ELSE NULL
        END AS unit_price,
        CASE
            WHEN discount_text ~ '^-?[0-9]+$'
                THEN ABS(discount_text::numeric)
            ELSE 0::numeric
        END AS discount_amount,
        CASE
            WHEN net_addon_text ~ '^-?[0-9]+$'
                THEN net_addon_text::numeric
            ELSE NULL
        END AS net_addon_amount,
        source_filename
    FROM source_raw
    WHERE LOWER(COALESCE(source_sku_code, '')) IN (
        'kemasanextra',
        'babelwrap',
        'bubble wrap',
        'packing'
    )
),
marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE LOWER(marketplace_name) = 'shopee'
    LIMIT 1
),
resolved_rows AS (
    SELECT
        s.*,
        COALESCE(ds.store_id, alias_store.store_id) AS store_id
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
    WHERE s.external_order_id IS NOT NULL
      AND COALESCE(ds.store_id, alias_store.store_id) IS NOT NULL
),
addon_rows AS (
    SELECT DISTINCT ON (
        fso.sales_order_id,
        MD5(CONCAT_WS(
            '|',
            r.external_order_id,
            r.normalized_store_name,
            COALESCE(r.source_sku_code, ''),
            COALESCE(r.source_addon_name, ''),
            COALESCE(r.source_variation_name, ''),
            COALESCE(r.quantity::text, ''),
            COALESCE(r.unit_price::text, ''),
            COALESCE(r.net_addon_amount::text, '')
        ))
    )
        fso.sales_order_id,
        MD5(CONCAT_WS(
            '|',
            r.external_order_id,
            r.normalized_store_name,
            COALESCE(r.source_sku_code, ''),
            COALESCE(r.source_addon_name, ''),
            COALESCE(r.source_variation_name, ''),
            COALESCE(r.quantity::text, ''),
            COALESCE(r.unit_price::text, ''),
            COALESCE(r.net_addon_amount::text, '')
        )) AS source_line_id,
        'packaging'::text AS addon_type,
        r.source_sku_code,
        r.source_addon_name,
        r.source_variation_name,
        r.quantity,
        'PCS'::text AS unit,
        r.unit_price,
        COALESCE(r.unit_price, 0) * COALESCE(r.quantity, 0) AS gross_addon_amount,
        r.discount_amount,
        COALESCE(
            r.net_addon_amount,
            (COALESCE(r.unit_price, 0) * COALESCE(r.quantity, 0)) - COALESCE(r.discount_amount, 0)
        ) AS net_addon_amount,
        r.addon_status,
        r.source_filename AS source_file
    FROM resolved_rows r
    JOIN {target_schema}.fact_sales_order fso
        ON fso.source_system = 'shopee'
       AND fso.sales_channel_type = 'online'
       AND fso.external_order_id = r.external_order_id
       AND fso.store_id = r.store_id
    ORDER BY
        fso.sales_order_id,
        MD5(CONCAT_WS(
            '|',
            r.external_order_id,
            r.normalized_store_name,
            COALESCE(r.source_sku_code, ''),
            COALESCE(r.source_addon_name, ''),
            COALESCE(r.source_variation_name, ''),
            COALESCE(r.quantity::text, ''),
            COALESCE(r.unit_price::text, ''),
            COALESCE(r.net_addon_amount::text, '')
        )),
        r.source_filename DESC
)
INSERT INTO {target_schema}.fact_sales_order_addon (
    sales_order_id,
    source_line_id,
    addon_type,
    source_sku_code,
    source_addon_name,
    source_variation_name,
    quantity,
    unit,
    unit_price,
    gross_addon_amount,
    discount_amount,
    net_addon_amount,
    addon_status,
    source_file,
    notes
)
SELECT
    sales_order_id,
    source_line_id,
    addon_type,
    source_sku_code,
    source_addon_name,
    source_variation_name,
    quantity,
    unit,
    unit_price,
    gross_addon_amount,
    discount_amount,
    net_addon_amount,
    addon_status,
    source_file,
    'Loaded by scripts/transform/sales_phase_1.py'
FROM addon_rows
ON CONFLICT DO NOTHING;
