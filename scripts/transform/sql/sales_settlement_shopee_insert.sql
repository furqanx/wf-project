WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(no_pesanan), ''), 'nan'), '-') AS external_order_id,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(waktu_pesanan_dibuat), ''), 'nan'), '-') AS order_created_at_text,
        NULLIF(NULLIF(NULLIF(TRIM(tanggal_dana_dilepaskan), ''), 'nan'), '-') AS released_at_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(harga_asli_produk), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS gross_revenue_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(jumlah_pengembalian_dana_ke_pembeli), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS refund_amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_diskon_produk), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS seller_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(diskon_produk_dari_shopee), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS platform_discount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(ongkir_dibayar_pembeli), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS shipping_amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_penghasilan), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS settlement_amount_text,
        source_filename
    FROM {staging_schema}.shopee_income_main
),
source_rows AS (
    SELECT
        external_order_id,
        normalized_store_name,
        CASE WHEN order_created_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN order_created_at_text::timestamp
        END AS order_created_at,
        CASE WHEN released_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN released_at_text::timestamp
        END AS released_at,
        CASE WHEN gross_revenue_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN gross_revenue_text::numeric ELSE NULL END AS gross_revenue_amount,
        CASE WHEN refund_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN refund_amount_text::numeric ELSE 0 END AS refund_amount,
        CASE WHEN seller_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN ABS(seller_discount_text::numeric) ELSE 0 END AS seller_discount_amount,
        CASE WHEN platform_discount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN ABS(platform_discount_text::numeric) ELSE 0 END AS platform_discount_amount,
        CASE WHEN shipping_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN shipping_amount_text::numeric ELSE 0 END AS shipping_amount,
        CASE WHEN settlement_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN settlement_amount_text::numeric ELSE NULL END AS settlement_amount,
        source_filename
    FROM source_raw
),
marketplace AS (
    SELECT marketplace_id
    FROM {target_schema}.dim_marketplace
    WHERE marketplace_code = 'shopee'
    LIMIT 1
),
unique_order_matches AS (
    SELECT
        external_order_id,
        MIN(sales_order_id) AS sales_order_id,
        MIN(store_id) AS store_id
    FROM {target_schema}.fact_sales_order
    WHERE source_system = 'shopee'
      AND sales_channel_type = 'online'
      AND external_order_id IS NOT NULL
    GROUP BY external_order_id
    HAVING COUNT(*) = 1
),
resolved_rows AS (
    SELECT
        s.*,
        m.marketplace_id,
        COALESCE(ds.store_id, alias_store.store_id) AS store_id,
        CASE
            WHEN fso.sales_order_id IS NULL
             AND unique_fso.sales_order_id IS NOT NULL
             AND unique_fso.store_id <> COALESCE(ds.store_id, alias_store.store_id)
                THEN unique_fso.sales_order_id
            ELSE fso.sales_order_id
        END AS sales_order_id,
        CASE
            WHEN fso.sales_order_id IS NULL
             AND unique_fso.sales_order_id IS NOT NULL
             AND unique_fso.store_id <> COALESCE(ds.store_id, alias_store.store_id)
                THEN TRUE
            ELSE FALSE
        END AS matched_by_order_id_fallback
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
    LEFT JOIN {target_schema}.fact_sales_order fso
        ON fso.source_system = 'shopee'
       AND fso.sales_channel_type = 'online'
       AND fso.external_order_id = s.external_order_id
       AND fso.store_id = COALESCE(ds.store_id, alias_store.store_id)
    LEFT JOIN unique_order_matches unique_fso
        ON unique_fso.external_order_id = s.external_order_id
    WHERE s.external_order_id IS NOT NULL
      AND COALESCE(ds.store_id, alias_store.store_id) IS NOT NULL
),
settlement_rows AS (
    SELECT DISTINCT ON (marketplace_id, store_id, external_order_id)
        'shopee'::text AS source_system,
        'online'::text AS sales_channel_type,
        marketplace_id,
        store_id,
        sales_order_id,
        external_order_id,
        'order_settlement'::text AS settlement_type,
        order_created_at,
        released_at AS settled_at,
        released_at,
        'IDR'::text AS currency_code,
        gross_revenue_amount,
        refund_amount,
        seller_discount_amount,
        platform_discount_amount,
        shipping_amount,
        settlement_amount,
        source_filename AS source_file,
        matched_by_order_id_fallback
    FROM resolved_rows
    ORDER BY marketplace_id, store_id, external_order_id, released_at DESC NULLS LAST, source_filename DESC
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
    released_at,
    currency_code,
    gross_revenue_amount,
    refund_amount,
    seller_discount_amount,
    platform_discount_amount,
    shipping_amount,
    settlement_amount,
    source_file,
    CASE
        WHEN sales_order_id IS NULL
            THEN 'Loaded by scripts/transform/sales_settlement_phase_2.py; phase_1_match_status=unmatched; unmatched_reason=missing_order_source'
        WHEN matched_by_order_id_fallback
            THEN 'Loaded by scripts/transform/sales_settlement_phase_2.py; phase_1_match_status=matched_by_unique_order_id_fallback'
        ELSE 'Loaded by scripts/transform/sales_settlement_phase_2.py; phase_1_match_status=matched_by_order_id_and_store'
    END
FROM settlement_rows
ON CONFLICT DO NOTHING;
