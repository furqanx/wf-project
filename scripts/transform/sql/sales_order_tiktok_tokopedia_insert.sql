WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_id), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(tokopedia_invoice_number), ''), 'nan'), '-') AS external_invoice_id,
        NULLIF(NULLIF(NULLIF(TRIM(order_status), ''), 'nan'), '-') AS order_status,
        NULLIF(NULLIF(NULLIF(TRIM(order_substatus), ''), 'nan'), '-') AS payment_status,
        NULLIF(NULLIF(NULLIF(TRIM(created_time), ''), 'nan'), '-') AS order_datetime_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_subtotal_before_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS sku_subtotal_before_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_platform_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS sku_platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(sku_seller_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS sku_seller_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(payment_platform_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS payment_platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(shipping_fee_after_discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS shipping_fee_after_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(order_amount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS order_amount_text,
        source_filename
    FROM {staging_schema}.tiktok_tokopedia_orders
),
source_rows AS (
    SELECT
        external_order_id,
        normalized_store_name,
        external_invoice_id,
        order_status,
        payment_status,
        CASE
            WHEN order_datetime_text ~ '^[0-9]{{1,2}}/[0-9]{{1,2}}/[0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}'
                THEN to_timestamp(order_datetime_text, 'DD/MM/YYYY HH24:MI:SS')
            WHEN order_datetime_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
                THEN order_datetime_text::timestamp
            ELSE NULL
        END AS order_datetime,
        CASE
            WHEN sku_subtotal_before_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN sku_subtotal_before_discount_text::numeric
            ELSE 0::numeric
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
            WHEN shipping_fee_after_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN shipping_fee_after_discount_text::numeric
            ELSE 0::numeric
        END AS shipping_fee_amount,
        CASE
            WHEN order_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN order_amount_text::numeric
            ELSE NULL
        END AS order_amount,
        source_filename
    FROM source_raw
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
        m.marketplace_id,
        sl.store_id
    FROM source_rows s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
    WHERE s.external_order_id IS NOT NULL
      AND sl.store_id IS NOT NULL
),
order_rows AS (
    SELECT
        'tiktok_tokopedia'::text AS source_system,
        'marketplace_order'::text AS source_order_type,
        'online'::text AS sales_channel_type,
        marketplace_id,
        store_id,
        external_order_id,
        MAX(external_invoice_id) AS external_invoice_id,
        MIN(order_datetime)::date AS order_date,
        MIN(order_datetime) AS order_datetime,
        MAX(order_status) AS order_status,
        MAX(payment_status) AS payment_status,
        'IDR'::text AS currency_code,
        SUM(COALESCE(gross_item_amount, 0)) AS gross_order_amount,
        SUM(
            COALESCE(platform_discount_amount, 0)
            + COALESCE(seller_discount_amount, 0)
            + COALESCE(payment_platform_discount_amount, 0)
        ) AS discount_amount,
        MAX(COALESCE(shipping_fee_amount, 0)) AS shipping_fee_amount,
        MAX(order_amount) AS net_order_amount,
        STRING_AGG(DISTINCT source_filename, ' | ' ORDER BY source_filename) AS source_file
    FROM resolved_rows
    GROUP BY marketplace_id, store_id, external_order_id
)
INSERT INTO {target_schema}.fact_sales_order (
    source_system,
    source_order_type,
    sales_channel_type,
    marketplace_id,
    store_id,
    external_order_id,
    external_invoice_id,
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
    external_invoice_id,
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
