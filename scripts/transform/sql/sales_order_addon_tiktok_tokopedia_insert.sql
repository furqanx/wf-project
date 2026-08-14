WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_id), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        COALESCE(
            NULLIF(NULLIF(NULLIF(TRIM(seller_sku), ''), 'nan'), '-'),
            NULLIF(NULLIF(NULLIF(TRIM(sku_id), ''), 'nan'), '-')
        ) AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(product_name), ''), 'nan'), '-') AS source_addon_name,
        NULLIF(NULLIF(NULLIF(TRIM(variation), ''), 'nan'), '-') AS source_variation_name,
        NULLIF(NULLIF(NULLIF(TRIM(order_status), ''), 'nan'), '-') AS addon_status,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(quantity), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS quantity_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_unit_original_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS unit_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_platform_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_seller_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS seller_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_subtotal_after_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS net_addon_text,
        source_filename
    FROM {staging_schema}.tiktok_tokopedia_orders
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
            WHEN quantity_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN quantity_text::numeric
            ELSE NULL
        END AS quantity,
        CASE
            WHEN unit_price_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN unit_price_text::numeric
            ELSE NULL
        END AS unit_price,
        CASE
            WHEN platform_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(platform_discount_text::numeric)
            ELSE 0::numeric
        END
        + CASE
            WHEN seller_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(seller_discount_text::numeric)
            ELSE 0::numeric
        END AS discount_amount,
        CASE
            WHEN net_addon_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN net_addon_text::numeric
            ELSE NULL
        END AS net_addon_amount,
        source_filename
    FROM source_raw
    WHERE LOWER(COALESCE(source_sku_code, '')) IN (
        'bubblewrap tambahan untuk keamanan packing',
        'tambahan packing extra bubble wrap',
        'kemasanextra'
    )
       OR LOWER(COALESCE(source_addon_name, '')) LIKE '%bubblewrap%'
       OR LOWER(COALESCE(source_addon_name, '')) LIKE '%bubble wrap%'
       OR LOWER(COALESCE(source_addon_name, '')) LIKE '%packing extra%'
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
        sl.store_id
    FROM source_rows s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
    WHERE s.external_order_id IS NOT NULL
      AND sl.store_id IS NOT NULL
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
        ON fso.source_system = 'tiktok_tokopedia'
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
