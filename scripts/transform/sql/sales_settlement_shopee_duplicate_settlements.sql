WITH source_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(no_pesanan), ''), 'nan'), '-') AS external_order_id,
        TRIM(store_name) AS store_name,
        LOWER(REGEXP_REPLACE(TRIM(store_name), '[^a-zA-Z0-9]+', '_', 'g')) AS normalized_store_name,
        NULLIF(NULLIF(NULLIF(TRIM(waktu_pesanan_dibuat), ''), 'nan'), '-') AS order_created_at_text,
        NULLIF(NULLIF(NULLIF(TRIM(tanggal_dana_dilepaskan), ''), 'nan'), '-') AS released_at_text,
        NULLIF(REPLACE(REGEXP_REPLACE(TRIM(total_penghasilan), '[^0-9.,-]+', '', 'g'), ',', ''), '') AS settlement_amount_text,
        source_filename
    FROM {staging_schema}.shopee_income_main
),
duplicate_grains AS (
    SELECT
        external_order_id,
        normalized_store_name,
        COUNT(*) AS row_count
    FROM source_rows
    WHERE external_order_id IS NOT NULL
    GROUP BY external_order_id, normalized_store_name
    HAVING COUNT(*) > 1
)
SELECT
    s.store_name,
    s.normalized_store_name,
    s.external_order_id,
    d.row_count,
    s.order_created_at_text,
    s.released_at_text,
    s.settlement_amount_text,
    s.source_filename
FROM source_rows s
JOIN duplicate_grains d
  ON d.external_order_id = s.external_order_id
 AND d.normalized_store_name = s.normalized_store_name
ORDER BY d.row_count DESC, s.normalized_store_name, s.external_order_id, s.released_at_text, s.source_filename;
