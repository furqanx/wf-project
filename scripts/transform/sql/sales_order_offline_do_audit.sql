WITH header_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(b2b_partner_id), ''), 'nan'), '-') AS source_b2b_partner_id
    FROM {staging_schema}.offline_do_header
),
item_rows AS (
    SELECT
        NULLIF(NULLIF(NULLIF(TRIM(item_id), ''), 'nan'), '-') AS source_line_id,
        NULLIF(NULLIF(NULLIF(TRIM(do_number), ''), 'nan'), '-') AS external_order_id,
        NULLIF(NULLIF(NULLIF(TRIM(sku), ''), 'nan'), '-') AS source_sku_code
    FROM {staging_schema}.offline_do_item
),
resolved_header AS (
    SELECT
        h.*,
        dbp.b2b_partner_id
    FROM header_rows h
    LEFT JOIN {target_schema}.dim_b2b_partner dbp
        ON dbp.b2b_partner_id::text = h.source_b2b_partner_id
    WHERE h.external_order_id IS NOT NULL
),
resolved_item AS (
    SELECT
        i.*,
        h.external_order_id AS header_external_order_id,
        psa.product_sku_alias_id
    FROM item_rows i
    LEFT JOIN header_rows h
        ON h.external_order_id = i.external_order_id
    LEFT JOIN {target_schema}.product_sku_alias psa
        ON LOWER(psa.sku_code) = LOWER(i.source_sku_code)
       AND psa.is_active
    WHERE i.external_order_id IS NOT NULL
),
duplicate_orders AS (
    SELECT
        external_order_id,
        COUNT(*) AS row_count
    FROM resolved_header
    GROUP BY external_order_id
    HAVING COUNT(*) > 1
),
duplicate_items AS (
    SELECT
        external_order_id,
        COALESCE(source_line_id, ''),
        COALESCE(source_sku_code, ''),
        COUNT(*) AS row_count
    FROM resolved_item
    GROUP BY external_order_id, COALESCE(source_line_id, ''), COALESCE(source_sku_code, '')
    HAVING COUNT(*) > 1
)
SELECT 'source_header_rows' AS metric, COUNT(*)::bigint AS value, 'Rows with usable DO number from offline DO header CSV.' AS notes
FROM resolved_header
UNION ALL
SELECT 'source_orders', COUNT(DISTINCT external_order_id)::bigint, 'Distinct offline DO order grain.'
FROM resolved_header
UNION ALL
SELECT 'source_item_rows', COUNT(*)::bigint, 'Rows with usable DO number from offline DO item CSV.'
FROM resolved_item
UNION ALL
SELECT 'unmapped_partner_rows', COUNT(*)::bigint, 'Header rows whose b2b_partner_id does not resolve to dim_b2b_partner.'
FROM resolved_header
WHERE source_b2b_partner_id IS NOT NULL
  AND b2b_partner_id IS NULL
UNION ALL
SELECT 'unmapped_product_rows', COUNT(*)::bigint, 'Item rows whose sku does not resolve to product_sku_alias.'
FROM resolved_item
WHERE source_sku_code IS NOT NULL
  AND product_sku_alias_id IS NULL
UNION ALL
SELECT 'item_without_header_rows', COUNT(*)::bigint, 'Item rows whose do_number does not exist in header CSV.'
FROM resolved_item
WHERE header_external_order_id IS NULL
UNION ALL
SELECT 'header_without_item_rows', COUNT(*)::bigint, 'Header rows without matching item rows.'
FROM resolved_header h
WHERE NOT EXISTS (
    SELECT 1
    FROM resolved_item i
    WHERE i.external_order_id = h.external_order_id
)
UNION ALL
SELECT 'duplicate_source_order_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Extra header rows per DO number.'
FROM duplicate_orders
UNION ALL
SELECT 'duplicate_source_item_extra_rows', COALESCE(SUM(row_count - 1), 0)::bigint, 'Potential duplicated item lines by DO number/source line/SKU.'
FROM duplicate_items;
