WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(item_id), ''), 'nan'), '-') AS source_line_id,
        NULLIF(NULLIF(NULLIF(TRIM(do_id), ''), 'nan'), '-') AS source_do_id,
        NULLIF(NULLIF(NULLIF(TRIM(do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(sku), ''), 'nan'), '-') AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(product_name_raw), ''), 'nan'), '-') AS source_product_name,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(qty), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS quantity_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(unit_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS unit_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS total_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_price_after_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS total_price_after_discount_text,
        source_filename
    FROM {staging_schema}.offline_do_item
),
source_rows AS (
    SELECT
        source_line_id,
        source_do_id,
        external_order_id,
        source_sku_code,
        source_product_name,
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
            WHEN total_price_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN total_price_text::numeric
            ELSE NULL
        END AS gross_item_amount,
        CASE
            WHEN total_price_after_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN total_price_after_discount_text::numeric
            ELSE NULL
        END AS net_item_amount,
        source_filename
    FROM source_raw
),
header_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(b2b_partner_id), ''), 'nan'), '-') AS source_b2b_partner_id,
        CASE
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(channel), ''), 'nan'), '-')) = 'offline' THEN 'offline'
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(channel), ''), 'nan'), '-')) = 'online' THEN 'online'
            WHEN LOWER(NULLIF(NULLIF(NULLIF(TRIM(channel), ''), 'nan'), '-')) = 'sample' THEN 'sample'
            ELSE COALESCE(LOWER(NULLIF(NULLIF(NULLIF(TRIM(channel), ''), 'nan'), '-')), 'offline')
        END AS sales_channel_type
    FROM {staging_schema}.offline_do_header
),
resolved_rows AS (
    SELECT
        s.*,
        psa.product_id,
        psa.product_sku_alias_id,
        COALESCE(psa.unit, dp.base_unit, 'PCS') AS unit,
        h.sales_channel_type,
        dbp.b2b_partner_id
    FROM source_rows s
    JOIN header_rows h
        ON h.external_order_id = s.external_order_id
    JOIN {target_schema}.dim_b2b_partner dbp
        ON dbp.b2b_partner_id::text = h.source_b2b_partner_id
    LEFT JOIN {target_schema}.product_sku_alias psa
        ON LOWER(psa.sku_code) = LOWER(s.source_sku_code)
       AND psa.is_active
    LEFT JOIN {target_schema}.dim_product dp
        ON dp.product_id = psa.product_id
    WHERE s.external_order_id IS NOT NULL
      AND psa.product_sku_alias_id IS NOT NULL
),
item_rows AS (
    SELECT DISTINCT ON (
        fso.sales_order_id,
        r.source_line_id,
        COALESCE(r.source_sku_code, ''),
        COALESCE(r.source_product_name, '')
    )
        fso.sales_order_id,
        r.source_line_id,
        r.product_id,
        r.product_sku_alias_id,
        r.source_sku_code,
        r.source_product_name,
        r.quantity,
        0::numeric AS quantity_returned,
        r.unit,
        r.unit_price,
        COALESCE(r.gross_item_amount, r.unit_price * r.quantity) AS gross_item_amount,
        GREATEST(
            COALESCE(r.gross_item_amount, r.unit_price * r.quantity)
            - COALESCE(r.net_item_amount, COALESCE(r.gross_item_amount, r.unit_price * r.quantity)),
            0
        ) AS discount_amount,
        COALESCE(r.net_item_amount, COALESCE(r.gross_item_amount, r.unit_price * r.quantity)) AS net_item_amount,
        r.source_filename AS source_file,
        r.source_do_id AS raw_record_id
    FROM resolved_rows r
    JOIN {target_schema}.fact_sales_order fso
        ON fso.source_system = 'offline_do'
       AND fso.sales_channel_type = r.sales_channel_type
       AND fso.external_order_id = r.external_order_id
       AND fso.b2b_partner_id = r.b2b_partner_id
    ORDER BY
        fso.sales_order_id,
        r.source_line_id,
        COALESCE(r.source_sku_code, ''),
        COALESCE(r.source_product_name, ''),
        r.source_filename DESC
)
INSERT INTO {target_schema}.fact_sales_order_item (
    sales_order_id,
    source_line_id,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    quantity,
    quantity_returned,
    unit,
    unit_price,
    gross_item_amount,
    discount_amount,
    net_item_amount,
    source_file,
    raw_record_id,
    notes
)
SELECT
    sales_order_id,
    source_line_id,
    product_id,
    product_sku_alias_id,
    source_sku_code,
    source_product_name,
    quantity,
    quantity_returned,
    unit,
    unit_price,
    gross_item_amount,
    discount_amount,
    net_item_amount,
    source_file,
    raw_record_id,
    'Loaded by scripts/transform/offline_sales.py'
FROM item_rows
ON CONFLICT DO NOTHING;
