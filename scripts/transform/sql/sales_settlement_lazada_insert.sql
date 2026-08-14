WITH source_raw AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(nomor_pesanan), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(id_pesanan), ''), 'nan'), '-') AS external_order_item_id,
        NULLIF(NULLIF(NULLIF(TRIM(sku_penjual), ''), 'nan'), '-') AS source_sku_code,
        NULLIF(NULLIF(NULLIF(TRIM(nama_biaya), ''), 'nan'), '-') AS fee_name,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(tanggal_pesanan_dibuat), ''), 'nan'), '-') AS order_created_at_text,
        NULLIF(NULLIF(NULLIF(TRIM(tanggal_transaksi), ''), 'nan'), '-') AS transaction_at_text,
        NULLIF(NULLIF(NULLIF(TRIM(tanggal_dilepas), ''), 'nan'), '-') AS released_at_text,
        NULLIF(NULLIF(NULLIF(TRIM(status_pelepasan_dana), ''), 'nan'), '-') AS settlement_status,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(jumlah_termasuk_pajak), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(vat_amount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS vat_amount_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(wht_amount), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS wht_amount_text,
        source_filename
    FROM {staging_schema}.lazada_income
),
source_rows AS (
    SELECT
        external_order_id,
        external_order_item_id,
        source_sku_code,
        fee_name,
        normalized_store_name,
        CASE WHEN order_created_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN order_created_at_text::timestamp
        END AS order_created_at,
        CASE
            WHEN transaction_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN transaction_at_text::timestamp
            WHEN transaction_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}}$' THEN to_timestamp(transaction_at_text, 'DD Mon YYYY')
            WHEN transaction_at_text IS NOT NULL THEN to_timestamp(transaction_at_text, 'DD Mon YYYY HH24:MI')
        END AS settled_at,
        CASE
            WHEN released_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN released_at_text::timestamp
            WHEN released_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}}$' THEN to_timestamp(released_at_text, 'DD Mon YYYY')
            WHEN released_at_text IS NOT NULL THEN to_timestamp(released_at_text, 'DD Mon YYYY HH24:MI')
        END AS released_at,
        settlement_status,
        CASE WHEN amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN amount_text::numeric ELSE 0 END AS amount,
        CASE WHEN vat_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN vat_amount_text::numeric ELSE 0 END AS vat_amount,
        CASE WHEN wht_amount_text ~ '^-?[0-9]+(\.[0-9]+)?$' THEN wht_amount_text::numeric ELSE 0 END AS wht_amount,
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
        COALESCE(ds.store_id, alias_store.store_id) AS store_id,
        fso.sales_order_id
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
        ON fso.source_system = 'lazada'
       AND fso.sales_channel_type = 'online'
       AND fso.store_id = COALESCE(ds.store_id, alias_store.store_id)
       AND fso.external_order_id IN (s.external_order_id, s.external_order_item_id)
    WHERE COALESCE(s.external_order_id, s.external_order_item_id) IS NOT NULL
      AND COALESCE(ds.store_id, alias_store.store_id) IS NOT NULL
),
settlement_rows AS (
    SELECT
        'lazada'::text AS source_system,
        'online'::text AS sales_channel_type,
        marketplace_id,
        store_id,
        MIN(sales_order_id) AS sales_order_id,
        external_order_id,
        external_order_item_id,
        source_sku_code,
        'order_settlement'::text AS settlement_type,
        MAX(order_created_at) AS order_created_at,
        MAX(settled_at) AS settled_at,
        MAX(released_at) AS released_at,
        MAX(settlement_status) AS settlement_status,
        'IDR'::text AS currency_code,
        SUM(amount) AS settlement_amount,
        SUM(vat_amount) AS total_fee_amount,
        SUM(wht_amount) AS refund_amount,
        STRING_AGG(DISTINCT fee_name, ' | ' ORDER BY fee_name) AS fee_names,
        STRING_AGG(DISTINCT source_filename, ' | ' ORDER BY source_filename) AS source_file
    FROM resolved_rows
    GROUP BY marketplace_id, store_id, external_order_id, external_order_item_id, source_sku_code
)
INSERT INTO {target_schema}.fact_sales_settlement (
    source_system,
    sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    external_order_id,
    external_order_item_id,
    source_sku_code,
    settlement_type,
    order_created_at,
    settled_at,
    released_at,
    settlement_status,
    currency_code,
    refund_amount,
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
    COALESCE(external_order_id, external_order_item_id),
    external_order_item_id,
    source_sku_code,
    settlement_type,
    order_created_at,
    settled_at,
    released_at,
    settlement_status,
    currency_code,
    refund_amount,
    total_fee_amount,
    settlement_amount,
    source_file,
    CONCAT_WS(' | ', 'Loaded by scripts/transform/sales_settlement_phase_2.py', 'lazada_fee_names=' || fee_names)
FROM settlement_rows
ON CONFLICT DO NOTHING;
