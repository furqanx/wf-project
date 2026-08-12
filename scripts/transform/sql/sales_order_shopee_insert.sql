WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(no_pesanan), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(status_pesanan), ''), 'nan'), '-') AS order_status,
        NULLIF(NULLIF(NULLIF(TRIM(metode_pembayaran), ''), 'nan'), '-') AS payment_status,
        NULLIF(NULLIF(NULLIF(TRIM(waktu_pesanan_dibuat), ''), 'nan'), '-') AS order_datetime_text,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(total_pembayaran), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS total_payment_text,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(ongkos_kirim_dibayar_oleh_pembeli), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS shipping_fee_text,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(harga_awal), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS unit_price_text,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(jumlah), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS quantity_text,
        NULLIF(REGEXP_REPLACE(REPLACE(REPLACE(TRIM(total_diskon), '.', ''), ',', ''), '[^0-9-]+', '', 'g'), '') AS discount_text,
        source_filename
    FROM {staging_schema}.shopee_orders
),
source_rows AS (
    SELECT
        external_order_id,
        normalized_store_name,
        order_status,
        payment_status,
        CASE
            WHEN order_datetime_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
                THEN order_datetime_text::timestamp
            ELSE NULL
        END AS order_datetime,
        CASE
            WHEN total_payment_text ~ '^-?[0-9]+$'
                THEN total_payment_text::numeric
            ELSE NULL
        END AS total_payment_amount,
        CASE
            WHEN shipping_fee_text ~ '^-?[0-9]+$'
                THEN shipping_fee_text::numeric
            ELSE NULL
        END AS shipping_fee_amount,
        CASE
            WHEN unit_price_text ~ '^-?[0-9]+$'
                THEN unit_price_text::numeric
            ELSE NULL
        END AS unit_price,
        CASE
            WHEN quantity_text ~ '^-?[0-9]+$'
                THEN quantity_text::numeric
            ELSE NULL
        END AS quantity,
        CASE
            WHEN discount_text ~ '^-?[0-9]+$'
                THEN ABS(discount_text::numeric)
            ELSE 0::numeric
        END AS discount_amount,
        source_filename
    FROM source_raw
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
order_rows AS (
    SELECT
        'shopee'::text AS source_system,
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
        SUM(COALESCE(unit_price, 0) * COALESCE(quantity, 0)) AS gross_order_amount,
        SUM(COALESCE(discount_amount, 0)) AS discount_amount,
        MAX(shipping_fee_amount) AS shipping_fee_amount,
        MAX(total_payment_amount) AS net_order_amount,
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
