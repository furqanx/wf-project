WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(order_adjustment_id), ''), 'nan'), '-') AS external_order_id,
        LOWER(NULLIF(NULLIF(NULLIF(TRIM(type), ''), 'nan'), '-')) AS transaction_type,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(order_created_time), ''), 'nan'), '-') AS order_created_at_text,
        NULLIF(NULLIF(NULLIF(TRIM(order_settled_time), ''), 'nan'), '-') AS settled_at_text,
        NULLIF(NULLIF(NULLIF(TRIM(currency), ''), 'nan'), '-') AS currency_code,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_settlement_amount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS settlement_amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_revenue), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS gross_revenue_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_fees), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS total_fee_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(refund_subtotal_after_seller_discounts), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS refund_amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(seller_discounts), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS seller_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(platform_discounts), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(shipping_cost), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS shipping_amount_text,
        source_filename
    FROM {staging_schema}.tiktok_tokopedia_income
),
source_rows AS (
    SELECT
        external_order_id,
        transaction_type,
        normalized_store_name,
        CASE WHEN order_created_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN order_created_at_text::timestamp
            WHEN order_created_at_text ~ '^[0-9]{{4}}/[0-9]{{2}}/[0-9]{{2}}'
            THEN order_created_at_text::timestamp
        END AS order_created_at,
        CASE WHEN settled_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN settled_at_text::timestamp
            WHEN settled_at_text ~ '^[0-9]{{4}}/[0-9]{{2}}/[0-9]{{2}}'
            THEN settled_at_text::timestamp
        END AS settled_at,
        COALESCE(currency_code, 'IDR') AS currency_code,
        CASE WHEN settlement_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN settlement_amount_text::numeric ELSE NULL END AS settlement_amount,
        CASE WHEN gross_revenue_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN gross_revenue_text::numeric ELSE NULL END AS gross_revenue_amount,
        CASE WHEN total_fee_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN total_fee_text::numeric ELSE 0 END AS total_fee_amount,
        CASE WHEN refund_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN refund_amount_text::numeric ELSE 0 END AS refund_amount,
        CASE WHEN seller_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN ABS(seller_discount_text::numeric) ELSE 0 END AS seller_discount_amount,
        CASE WHEN platform_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN ABS(platform_discount_text::numeric) ELSE 0 END AS platform_discount_amount,
        CASE WHEN shipping_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN shipping_amount_text::numeric ELSE 0 END AS shipping_amount,
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
        sl.store_id,
        fso.sales_order_id
    FROM source_rows s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
    LEFT JOIN {target_schema}.fact_sales_order fso
        ON fso.source_system = 'tiktok_tokopedia'
       AND fso.sales_channel_type = 'online'
       AND fso.external_order_id = s.external_order_id
       AND fso.store_id = sl.store_id
    WHERE s.external_order_id IS NOT NULL
      AND COALESCE(s.transaction_type, '') IN ('order', 'pesanan')
      AND sl.store_id IS NOT NULL
),
settlement_rows AS (
    SELECT DISTINCT ON (marketplace_id, store_id, external_order_id)
        'tiktok_tokopedia'::text AS source_system,
        'online'::text AS sales_channel_type,
        marketplace_id,
        store_id,
        sales_order_id,
        external_order_id,
        'order_settlement'::text AS settlement_type,
        order_created_at,
        settled_at,
        currency_code,
        gross_revenue_amount,
        refund_amount,
        seller_discount_amount,
        platform_discount_amount,
        shipping_amount,
        total_fee_amount,
        settlement_amount,
        source_filename AS source_file
    FROM resolved_rows
    ORDER BY marketplace_id, store_id, external_order_id, settled_at DESC NULLS LAST, source_filename DESC
)
INSERT INTO {target_schema}.fact_sales_settlement (
    source_system,
    sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    external_order_id,
    settlement_type,
    order_created_at,
    settled_at,
    released_at,
    currency_code,
    gross_revenue_amount,
    refund_amount,
    seller_discount_amount,
    platform_discount_amount,
    shipping_amount,
    total_fee_amount,
    settlement_amount,
    source_file,
    notes
)
SELECT
    source_system,
    sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    external_order_id,
    settlement_type,
    order_created_at,
    settled_at,
    settled_at AS released_at,
    currency_code,
    gross_revenue_amount,
    refund_amount,
    seller_discount_amount,
    platform_discount_amount,
    shipping_amount,
    total_fee_amount,
    settlement_amount,
    source_file,
    'Loaded by scripts/transform/sales_settlement_phase_2.py'
FROM settlement_rows
ON CONFLICT DO NOTHING;
