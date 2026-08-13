WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_id), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(sku_id), ''), 'nan'), '-') AS sku_id,
        NULLIF(NULLIF(NULLIF(TRIM(seller_sku), ''), 'nan'), '-') AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(product_name), ''), 'nan'), '-') AS source_product_name,
        NULLIF(NULLIF(NULLIF(TRIM(variation), ''), 'nan'), '-') AS source_variation_name,
        NULLIF(NULLIF(NULLIF(TRIM(order_status), ''), 'nan'), '-') AS item_status,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(quantity), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS quantity_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_quantity_of_return), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS quantity_returned_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_unit_original_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS unit_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_subtotal_before_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS gross_item_amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_platform_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS sku_platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_seller_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS sku_seller_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(payment_platform_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS payment_platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_subtotal_after_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS net_item_amount_text,
        source_filename
    FROM {staging_schema}.tiktok_tokopedia_orders
),
source_rows AS (
    SELECT
        external_order_id,
        normalized_store_name,
        COALESCE(
            sku_id,
            MD5(CONCAT_WS('|', external_order_id, normalized_store_name, COALESCE(source_sku_code, ''), COALESCE(source_product_name, ''), COALESCE(source_variation_name, ''), source_filename))
        ) AS source_line_id,
        sku_id,
        source_sku_code,
        source_product_name,
        source_variation_name,
        item_status,
        CASE
            WHEN quantity_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN quantity_text::numeric
            ELSE 1::numeric
        END AS quantity,
        CASE
            WHEN quantity_returned_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN quantity_returned_text::numeric
            ELSE 0::numeric
        END AS quantity_returned,
        CASE
            WHEN unit_price_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN unit_price_text::numeric
            ELSE NULL
        END AS unit_price,
        CASE
            WHEN gross_item_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN gross_item_amount_text::numeric
            ELSE NULL
        END AS gross_item_amount,
        CASE
            WHEN sku_platform_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(sku_platform_discount_text::numeric)
            ELSE 0::numeric
        END AS platform_discount_amount,
        CASE
            WHEN sku_seller_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(sku_seller_discount_text::numeric)
            ELSE 0::numeric
        END AS seller_discount_amount,
        CASE
            WHEN payment_platform_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(payment_platform_discount_text::numeric)
            ELSE 0::numeric
        END AS payment_platform_discount_amount,
        CASE
            WHEN net_item_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN net_item_amount_text::numeric
            ELSE NULL
        END AS net_item_amount,
        source_filename
    FROM source_raw
),
marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE marketplace_code = 'tiktok_tokopedia'
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
    LEFT JOIN LATERAL (
        SELECT
            pma.product_id,
            pma.product_sku_alias_id
        FROM {target_schema}.product_marketplace_alias pma
        WHERE pma.marketplace_code IN ('tiktok_tokopedia', 'tiktok')
          AND pma.is_active
          AND (
            LOWER(pma.raw_alias) = LOWER(s.source_sku_code)
            OR LOWER(pma.source_sku_code) = LOWER(s.source_sku_code)
            OR LOWER(pma.mapped_source_sku_code) = LOWER(s.source_sku_code)
            OR LOWER(pma.normalized_alias) = LOWER(s.source_sku_code)
          )
        ORDER BY pma.product_marketplace_alias_id
        LIMIT 1
    ) pma ON TRUE
    LEFT JOIN LATERAL (
        SELECT
            psa.product_id,
            psa.product_sku_alias_id
        FROM {target_schema}.product_sku_alias psa
        WHERE psa.sku_code = s.source_sku_code
          AND psa.is_active
        ORDER BY psa.product_sku_alias_id
        LIMIT 1
    ) psa ON TRUE
    WHERE s.external_order_id IS NOT NULL
      AND COALESCE(ds.store_id, alias_store.store_id) IS NOT NULL
      AND COALESCE(pma.product_sku_alias_id, psa.product_sku_alias_id) IS NOT NULL
),
item_rows AS (
    SELECT DISTINCT ON (
        fso.sales_order_id,
        r.source_line_id,
        COALESCE(r.source_sku_code, ''),
        COALESCE(r.source_product_name, ''),
        COALESCE(r.source_variation_name, '')
    )
        fso.sales_order_id,
        r.source_line_id,
        r.product_id,
        r.product_sku_alias_id,
        r.source_sku_code,
        r.source_product_name,
        r.source_variation_name,
        r.quantity,
        r.quantity_returned,
        'PCS'::text AS unit,
        r.unit_price,
        COALESCE(r.gross_item_amount, r.unit_price * r.quantity) AS gross_item_amount,
        COALESCE(r.platform_discount_amount, 0)
            + COALESCE(r.seller_discount_amount, 0)
            + COALESCE(r.payment_platform_discount_amount, 0) AS discount_amount,
        COALESCE(
            r.net_item_amount,
            COALESCE(r.gross_item_amount, r.unit_price * r.quantity)
            - COALESCE(r.platform_discount_amount, 0)
            - COALESCE(r.seller_discount_amount, 0)
            - COALESCE(r.payment_platform_discount_amount, 0)
        ) AS net_item_amount,
        r.item_status,
        r.source_filename AS source_file
    FROM resolved_rows r
    JOIN {target_schema}.fact_sales_order fso
        ON fso.source_system = 'tiktok_tokopedia'
       AND fso.sales_channel_type = 'online'
       AND fso.external_order_id = r.external_order_id
       AND fso.store_id = r.store_id
    ORDER BY
        fso.sales_order_id,
        r.source_line_id,
        COALESCE(r.source_sku_code, ''),
        COALESCE(r.source_product_name, ''),
        COALESCE(r.source_variation_name, ''),
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
