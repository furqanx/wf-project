WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_number), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(order_item_id), ''), 'nan'), '-') AS source_line_id,
        NULLIF(NULLIF(NULLIF(TRIM(status), ''), 'nan'), '-') AS order_status,
        NULLIF(NULLIF(NULLIF(TRIM(pay_method), ''), 'nan'), '-') AS payment_status,
        NULLIF(NULLIF(NULLIF(TRIM(create_time), ''), 'nan'), '-') AS order_datetime_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(paid_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS paid_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(unit_price), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS unit_price_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(seller_discount_total), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS seller_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(platform_discount_total), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(bundle_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS bundle_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(shipping_fee), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS shipping_fee_text,
        source_filename
    FROM {staging_schema}.lazada_orders
),
source_rows AS (
    SELECT
        external_order_id,
        normalized_store_name,
        COALESCE(
            source_line_id,
            MD5(CONCAT_WS('|', external_order_id, normalized_store_name, source_filename, paid_price_text, unit_price_text))
        ) AS source_line_id,
        order_status,
        payment_status,
        CASE
            WHEN order_datetime_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
                THEN order_datetime_text::timestamp
            WHEN order_datetime_text ~ '^[0-9]{{1,2}} [A-Za-z]{{3}} [0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}'
                THEN to_timestamp(order_datetime_text, 'DD Mon YYYY HH24:MI')
            ELSE NULL
        END AS order_datetime,
        CASE
            WHEN paid_price_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN paid_price_text::numeric
            ELSE NULL
        END AS paid_price,
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
            WHEN shipping_fee_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN shipping_fee_text::numeric
            ELSE 0::numeric
        END AS shipping_fee_amount,
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
        m.marketplace_id,
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
deduped_rows AS (
    SELECT DISTINCT ON (
        external_order_id,
        normalized_store_name,
        source_line_id
    )
        *
    FROM resolved_rows
    ORDER BY
        external_order_id,
        normalized_store_name,
        source_line_id,
        source_filename DESC
),
order_rows AS (
    SELECT
        'lazada'::text AS source_system,
        'marketplace_order'::text AS source_order_type,
        'online'::text AS sales_channel_type,
        marketplace_id,
        store_id,
        external_order_id,
        MIN(order_datetime)::date AS order_date,
        MIN(order_datetime) AS order_datetime,
        MAX(order_status) AS order_status,
        MAX(payment_status) AS payment_status,
        'IDR'::text AS currency_code,
        SUM(COALESCE(unit_price, 0)) AS gross_order_amount,
        SUM(COALESCE(seller_discount_amount, 0) + COALESCE(platform_discount_amount, 0) + COALESCE(bundle_discount_amount, 0)) AS discount_amount,
        SUM(COALESCE(shipping_fee_amount, 0)) AS shipping_fee_amount,
        SUM(COALESCE(paid_price, 0)) AS net_order_amount,
        STRING_AGG(DISTINCT source_filename, ' | ' ORDER BY source_filename) AS source_file
    FROM deduped_rows
    GROUP BY marketplace_id, store_id, external_order_id
)
INSERT INTO {target_schema}.fact_sales_order (
    source_system,
    source_order_type,
    sales_channel_type,
    marketplace_id,
    store_id,
    external_order_id,
    order_date,
    order_datetime,
    order_status,
    payment_status,
    currency_code,
    gross_order_amount,
    discount_amount,
    shipping_fee_amount,
    net_order_amount,
    source_file,
    notes
)
SELECT
    source_system,
    source_order_type,
    sales_channel_type,
    marketplace_id,
    store_id,
    external_order_id,
    order_date,
    order_datetime,
    order_status,
    payment_status,
    currency_code,
    gross_order_amount,
    discount_amount,
    shipping_fee_amount,
    net_order_amount,
    source_file,
    'Loaded by scripts/transform/sales_phase_1.py'
FROM order_rows
ON CONFLICT DO NOTHING;
