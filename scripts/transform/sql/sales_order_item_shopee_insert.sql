WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(no_pesanan), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        COALESCE(
            NULLIF(NULLIF(NULLIF(TRIM(nomor_referensi_sku), ''), 'nan'), '-'),
            NULLIF(NULLIF(NULLIF(TRIM(sku_induk), ''), 'nan'), '-')
        ) AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(nama_produk), ''), 'nan'), '-') AS source_product_name,
        NULLIF(NULLIF(NULLIF(TRIM(nama_variasi), ''), 'nan'), '-') AS source_variation_name,
        NULLIF(NULLIF(NULLIF(TRIM(status_pesanan), ''), 'nan'), '-') AS item_status,
        CASE
            WHEN NULLIF(NULLIF(NULLIF(TRIM(jumlah), ''), 'nan'), '-') IS NOT NULL
                THEN NULLIF(REPLACE(REPLACE(TRIM(jumlah), '.', ''), ',', ''), '')::numeric
            ELSE NULL
        END AS quantity,
        CASE
            WHEN NULLIF(NULLIF(NULLIF(TRIM(returned_quantity), ''), 'nan'), '-') IS NOT NULL
                THEN NULLIF(REPLACE(REPLACE(TRIM(returned_quantity), '.', ''), ',', ''), '')::numeric
            ELSE 0::numeric
        END AS quantity_returned,
        CASE
            WHEN NULLIF(NULLIF(NULLIF(TRIM(harga_awal), ''), 'nan'), '-') IS NOT NULL
                THEN NULLIF(REPLACE(REPLACE(TRIM(harga_awal), '.', ''), ',', ''), '')::numeric
            ELSE NULL
        END AS unit_price,
        CASE
            WHEN NULLIF(NULLIF(NULLIF(TRIM(total_diskon), ''), 'nan'), '-') IS NOT NULL
                THEN ABS(NULLIF(REPLACE(REPLACE(TRIM(total_diskon), '.', ''), ',', ''), '')::numeric)
            ELSE 0::numeric
        END AS discount_amount,
        CASE
            WHEN NULLIF(NULLIF(NULLIF(TRIM(total_harga_produk), ''), 'nan'), '-') IS NOT NULL
                THEN NULLIF(REPLACE(REPLACE(TRIM(total_harga_produk), '.', ''), ',', ''), '')::numeric
            ELSE NULL
        END AS net_item_amount,
        source_filename
    FROM {staging_schema}.shopee_orders
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
        COALESCE(ds.store_id, alias_store.store_id) AS store_id,
        COALESCE(pma.product_id, psa.product_id) AS product_id,
        COALESCE(pma.product_sku_alias_id, psa.product_sku_alias_id) AS product_sku_alias_id
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
    LEFT JOIN {target_schema}.product_marketplace_alias pma
        ON pma.marketplace_code = 'shopee'
       AND pma.is_active
       AND (
            LOWER(pma.raw_alias) = LOWER(s.source_sku_code)
            OR LOWER(pma.source_sku_code) = LOWER(s.source_sku_code)
            OR LOWER(pma.normalized_alias) = LOWER(s.source_sku_code)
       )
    LEFT JOIN {target_schema}.product_sku_alias psa
        ON psa.sku_code = s.source_sku_code
       AND psa.is_active
    WHERE s.external_order_id IS NOT NULL
      AND COALESCE(ds.store_id, alias_store.store_id) IS NOT NULL
      AND COALESCE(pma.product_sku_alias_id, psa.product_sku_alias_id) IS NOT NULL
),
item_rows AS (
    SELECT DISTINCT ON (
        fso.sales_order_id,
        MD5(CONCAT_WS(
            '|',
            r.external_order_id,
            r.normalized_store_name,
            COALESCE(r.source_sku_code, ''),
            COALESCE(r.source_product_name, ''),
            COALESCE(r.source_variation_name, ''),
            COALESCE(r.quantity::text, ''),
            COALESCE(r.unit_price::text, ''),
            COALESCE(r.net_item_amount::text, '')
        ))
    )
        fso.sales_order_id,
        MD5(CONCAT_WS(
            '|',
            r.external_order_id,
            r.normalized_store_name,
            COALESCE(r.source_sku_code, ''),
            COALESCE(r.source_product_name, ''),
            COALESCE(r.source_variation_name, ''),
            COALESCE(r.quantity::text, ''),
            COALESCE(r.unit_price::text, ''),
            COALESCE(r.net_item_amount::text, '')
        )) AS source_line_id,
        r.product_id,
        r.product_sku_alias_id,
        r.source_sku_code,
        r.source_product_name,
        r.source_variation_name,
        r.quantity,
        r.quantity_returned,
        'PCS'::text AS unit,
        r.unit_price,
        COALESCE(r.unit_price, 0) * COALESCE(r.quantity, 0) AS gross_item_amount,
        r.discount_amount,
        COALESCE(
            r.net_item_amount,
            (COALESCE(r.unit_price, 0) * COALESCE(r.quantity, 0)) - COALESCE(r.discount_amount, 0)
        ) AS net_item_amount,
        r.item_status,
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
            COALESCE(r.source_product_name, ''),
            COALESCE(r.source_variation_name, ''),
            COALESCE(r.quantity::text, ''),
            COALESCE(r.unit_price::text, ''),
            COALESCE(r.net_item_amount::text, '')
        )),
        r.source_filename DESC
)
INSERT INTO {target_schema}.fact_sales_order_item (
    sales_order_id,
    source_line_id,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    source_variation_name,
    quantity,
    quantity_returned,
    unit,
    unit_price,
    gross_item_amount,
    discount_amount,
    net_item_amount,
    item_status,
    source_file,
    notes
)
SELECT
    sales_order_id,
    source_line_id,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    source_variation_name,
    quantity,
    quantity_returned,
    unit,
    unit_price,
    gross_item_amount,
    discount_amount,
    net_item_amount,
    item_status,
    source_file,
    'Loaded by scripts/transform/sales_phase_1.py'
FROM item_rows
ON CONFLICT DO NOTHING;
