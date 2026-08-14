WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(do_id), ''), 'nan'), '-') AS source_do_id,
        NULLIF(NULLIF(NULLIF(TRIM(do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(do_date_id), ''), 'nan'), '-') AS do_date_text,
        NULLIF(NULLIF(NULLIF(TRIM(customer_name), ''), 'nan'), '-') AS customer_name,
        NULLIF(NULLIF(NULLIF(TRIM(b2b_partner_id), ''), 'nan'), '-') AS source_b2b_partner_id,
        NULLIF(NULLIF(NULLIF(TRIM(do_type), ''), 'nan'), '-') AS do_type,
        NULLIF(NULLIF(NULLIF(TRIM(channel), ''), 'nan'), '-') AS channel,
        NULLIF(NULLIF(NULLIF(TRIM(courier_raw), ''), 'nan'), '-') AS courier_raw,
        NULLIF(NULLIF(NULLIF(TRIM(warehouse_raw), ''), 'nan'), '-') AS warehouse_raw,
        NULLIF(NULLIF(NULLIF(TRIM(warehouse_id), ''), 'nan'), '-') AS source_warehouse_id,
        NULLIF(NULLIF(NULLIF(TRIM(invoice_number), ''), 'nan'), '-') AS external_invoice_id,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(invoice_amount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS invoice_amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(shipping_cost), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS shipping_cost_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(discount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS discount_text,
        NULLIF(NULLIF(NULLIF(TRIM(payment_status), ''), 'nan'), '-') AS payment_status,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_bill), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS total_bill_text,
        NULLIF(NULLIF(NULLIF(TRIM(region_raw), ''), 'nan'), '-') AS region_raw,
        NULLIF(NULLIF(NULLIF(TRIM(geography_id), ''), 'nan'), '-') AS source_location_id,
        NULLIF(NULLIF(NULLIF(TRIM(return_notes), ''), 'nan'), '-') AS return_notes,
        source_filename
    FROM {staging_schema}.offline_do_header
),
source_rows AS (
    SELECT
        source_do_id,
        external_order_id,
        CASE
            WHEN do_date_text ~ '^[0-9]{{8}}$'
                THEN to_date(do_date_text, 'YYYYMMDD')
            ELSE NULL
        END AS order_date,
        customer_name,
        source_b2b_partner_id,
        do_type,
        CASE
            WHEN LOWER(channel) = 'offline' THEN 'offline'
            WHEN LOWER(channel) = 'online' THEN 'online'
            WHEN LOWER(channel) = 'sample' THEN 'sample'
            ELSE COALESCE(LOWER(channel), 'offline')
        END AS sales_channel_type,
        courier_raw,
        warehouse_raw,
        source_warehouse_id,
        external_invoice_id,
        CASE
            WHEN invoice_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN invoice_amount_text::numeric
            ELSE NULL
        END AS invoice_amount,
        CASE
            WHEN shipping_cost_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN shipping_cost_text::numeric
            ELSE 0::numeric
        END AS shipping_cost,
        CASE
            WHEN discount_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN ABS(discount_text::numeric)
            ELSE 0::numeric
        END AS discount_amount,
        payment_status,
        CASE
            WHEN total_bill_text ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN total_bill_text::numeric
            ELSE NULL
        END AS total_bill,
        region_raw,
        source_location_id,
        return_notes,
        source_filename
    FROM source_raw
),
resolved_rows AS (
    SELECT
        s.*,
        dbp.b2b_partner_id
    FROM source_rows s
    LEFT JOIN {target_schema}.dim_b2b_partner dbp
        ON dbp.b2b_partner_id::text = s.source_b2b_partner_id
    WHERE s.external_order_id IS NOT NULL
      AND dbp.b2b_partner_id IS NOT NULL
),
order_rows AS (
    SELECT DISTINCT ON (external_order_id, sales_channel_type, b2b_partner_id)
        'offline_do'::text AS source_system,
        'delivery_order'::text AS source_order_type,
        sales_channel_type,
        b2b_partner_id,
        external_order_id,
        external_invoice_id,
        order_date,
        order_date::timestamp AS order_datetime,
        do_type AS order_status,
        payment_status,
        'IDR'::text AS currency_code,
        COALESCE(invoice_amount, 0) AS gross_order_amount,
        COALESCE(discount_amount, 0) AS discount_amount,
        COALESCE(shipping_cost, 0) AS shipping_fee_amount,
        COALESCE(
            total_bill,
            COALESCE(invoice_amount, 0) - COALESCE(discount_amount, 0) + COALESCE(shipping_cost, 0)
        ) AS net_order_amount,
        source_filename AS source_file,
        source_do_id AS raw_record_id,
        CONCAT_WS(
            ' | ',
            'Loaded by scripts/transform/offline_sales.py',
            'customer_name=' || customer_name,
            'courier=' || courier_raw,
            'warehouse=' || warehouse_raw,
            'region=' || region_raw,
            'location_id=' || source_location_id,
            'return_notes=' || return_notes
        ) AS notes
    FROM resolved_rows
    ORDER BY external_order_id, sales_channel_type, b2b_partner_id, source_filename DESC
)
INSERT INTO {target_schema}.fact_sales_order (
    source_system,
    source_order_type,
    sales_channel_type,
    b2b_partner_id,
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
    raw_record_id,
    notes
)
SELECT
    source_system,
    source_order_type,
    sales_channel_type,
    b2b_partner_id,
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
    raw_record_id,
    notes
FROM order_rows
ON CONFLICT DO NOTHING;
