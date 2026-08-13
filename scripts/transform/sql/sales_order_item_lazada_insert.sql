WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_number), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(order_item_id), ''), 'nan'), '-') AS source_line_id,
        COALESCE(
            NULLIF(NULLIF(NULLIF(TRIM(seller_sku), ''), 'nan'), '-'),
            NULLIF(NULLIF(NULLIF(TRIM(lazada_sku), ''), 'nan'), '-')
        ) AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(item_name), ''), 'nan'), '-') AS source_product_name,
        NULLIF(NULLIF(NULLIF(TRIM(variation), ''), 'nan'), '-') AS source_variation_name,
        NULLIF(NULLIF(NULLIF(TRIM(status), ''), 'nan'), '-') AS item_status,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(paid_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS paid_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(unit_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS unit_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(seller_discount_total), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS seller_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(platform_discount_total), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(bundle_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS bundle_discount_text,
        source_filename
    FROM {staging_schema}.lazada_orders
),
source_rows AS (
    SELECT
        external_order_id,
        normalized_store_name,
        COALESCE(
            source_line_id,
            MD5(CONCAT_WS('|', external_order_id, normalized_store_name, COALESCE(source_sku_code, ''), COALESCE(source_product_name, ''), COALESCE(source_variation_name, ''), source_filename))
        ) AS source_line_id,
        source_sku_code,
        source_product_name,
        source_variation_name,
        item_status,
        1::numeric AS quantity,
        CASE
            WHEN LOWER(COALESCE(item_status, '')) LIKE '%return%'
                THEN 1::numeric
            ELSE 0::numeric
        END AS quantity_returned,
        CASE
            WHEN unit_price_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN unit_price_text::numeric
            ELSE NULL
        END AS unit_price,
        CASE
            WHEN seller_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(seller_discount_text::numeric)
            ELSE 0::numeric
        END AS seller_discount_amount,
        CASE
            WHEN platform_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(platform_discount_text::numeric)
            ELSE 0::numeric
        END AS platform_discount_amount,
        CASE
            WHEN bundle_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(bundle_discount_text::numeric)
            ELSE 0::numeric
        END AS bundle_discount_amount,
        CASE
            WHEN paid_price_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN paid_price_text::numeric
            ELSE NULL
        END AS net_item_amount,
        source_filename
    FROM source_raw
),
marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE marketplace_code = 'lazada'
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
        WHERE pma.marketplace_code = 'lazada'
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
        r.source_line_id
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
        COALESCE(r.unit_price, 0) AS gross_item_amount,
        COALESCE(r.seller_discount_amount, 0) + COALESCE(r.platform_discount_amount, 0) + COALESCE(r.bundle_discount_amount, 0) AS discount_amount,
        COALESCE(
            r.net_item_amount,
            COALESCE(r.unit_price, 0)
            - COALESCE(r.seller_discount_amount, 0)
            - COALESCE(r.platform_discount_amount, 0)
            - COALESCE(r.bundle_discount_amount, 0)
        ) AS net_item_amount,
        r.item_status,
        r.source_filename AS source_file
    FROM resolved_rows r
    JOIN {target_schema}.fact_sales_order fso
        ON fso.source_system = 'lazada'
       AND fso.sales_channel_type = 'online'
       AND fso.external_order_id = r.external_order_id
       AND fso.store_id = r.store_id
    ORDER BY
        fso.sales_order_id,
        r.source_line_id,
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
