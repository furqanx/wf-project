WITH source_info AS (
    SELECT source_system
    FROM {staging_schema}.sales_return_source
    LIMIT 1
),
marketplace AS (
    SELECT dm.marketplace_id
    FROM {target_schema}.dim_marketplace dm
    JOIN source_info si
        ON si.source_system = dm.marketplace_code
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
marketplace_alias_lookup AS (
    SELECT DISTINCT ON (source_system, alias_code)
        source_system,
        alias_code,
        product_id,
        product_sku_alias_id
    FROM (
        SELECT
            CASE WHEN marketplace_code = 'tiktok' THEN 'tiktok_tokopedia' ELSE marketplace_code END AS source_system,
            LOWER(raw_alias) AS alias_code,
            product_id,
            product_sku_alias_id,
            product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE is_active
        UNION ALL
        SELECT
            CASE WHEN marketplace_code = 'tiktok' THEN 'tiktok_tokopedia' ELSE marketplace_code END AS source_system,
            LOWER(source_sku_code) AS alias_code,
            product_id,
            product_sku_alias_id,
            product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE is_active
        UNION ALL
        SELECT
            CASE WHEN marketplace_code = 'tiktok' THEN 'tiktok_tokopedia' ELSE marketplace_code END AS source_system,
            LOWER(mapped_source_sku_code) AS alias_code,
            product_id,
            product_sku_alias_id,
            product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE is_active
        UNION ALL
        SELECT
            CASE WHEN marketplace_code = 'tiktok' THEN 'tiktok_tokopedia' ELSE marketplace_code END AS source_system,
            LOWER(normalized_alias) AS alias_code,
            product_id,
            product_sku_alias_id,
            product_marketplace_alias_id
        FROM {target_schema}.product_marketplace_alias
        WHERE is_active
    ) aliases
    WHERE alias_code IS NOT NULL
    ORDER BY source_system, alias_code, product_marketplace_alias_id
),
sku_alias_lookup AS (
    SELECT DISTINCT ON (LOWER(sku_code))
        LOWER(sku_code) AS sku_code,
        product_id,
        product_sku_alias_id
    FROM {target_schema}.product_sku_alias
    WHERE is_active
    ORDER BY LOWER(sku_code), product_sku_alias_id
),
resolved_rows AS (
    SELECT
        s.*,
        m.marketplace_id,
        sl.store_id,
        COALESCE(pma.product_id, psa.product_id) AS product_id,
        COALESCE(pma.product_sku_alias_id, psa.product_sku_alias_id) AS product_sku_alias_id
    FROM {staging_schema}.sales_return_source s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
    LEFT JOIN marketplace_alias_lookup pma
        ON pma.source_system = s.source_system
       AND pma.alias_code = LOWER(s.source_sku_code)
    LEFT JOIN sku_alias_lookup psa
        ON psa.sku_code = LOWER(s.source_sku_code)
),
order_lookup AS (
    SELECT DISTINCT ON (
        fso.source_system,
        fso.store_id,
        fso.external_order_id
    )
        fso.source_system,
        fso.store_id,
        fso.external_order_id,
        fso.sales_order_id
    FROM {target_schema}.fact_sales_order fso
    JOIN resolved_rows r
        ON r.source_system = fso.source_system
       AND r.store_id = fso.store_id
       AND r.external_order_id = fso.external_order_id
    WHERE fso.sales_channel_type = 'online'
    ORDER BY fso.source_system, fso.store_id, fso.external_order_id, fso.sales_order_id
),
resolved_with_order AS (
    SELECT
        r.*,
        ol.sales_order_id
    FROM resolved_rows r
    LEFT JOIN order_lookup ol
        ON ol.source_system = r.source_system
       AND ol.store_id = r.store_id
       AND ol.external_order_id = r.external_order_id
),
order_item_lookup AS (
    SELECT DISTINCT ON (r.return_source_sequence)
        r.return_source_sequence,
        fsoi.sales_order_item_id
    FROM resolved_with_order r
    JOIN {target_schema}.fact_sales_order_item fsoi
        ON fsoi.sales_order_id = r.sales_order_id
       AND (
            fsoi.source_line_id = r.source_line_id
            OR (
                fsoi.product_id = r.product_id
                AND COALESCE(LOWER(fsoi.source_sku_code), '') = COALESCE(LOWER(r.source_sku_code), '')
            )
       )
    ORDER BY r.return_source_sequence, fsoi.sales_order_item_id
),
return_rows AS (
    SELECT DISTINCT ON (return_raw_record_id)
        source_system,
        'online'::text AS sales_channel_type,
        marketplace_id,
        store_id,
        sales_order_id,
        external_order_id,
        external_return_id,
        return_type,
        return_status,
        return_reason,
        return_initiator,
        return_requested_at,
        return_completed_at,
        currency_code,
        refund_amount,
        return_shipping_amount,
        source_file,
        source_sheet,
        source_row_number,
        return_raw_record_id AS raw_record_id
    FROM resolved_with_order
    WHERE store_id IS NOT NULL
    ORDER BY return_raw_record_id, source_file DESC, source_row_number DESC
),
upserted_returns AS (
    INSERT INTO {target_schema}.fact_sales_return (
        source_system,
        sales_channel_type,
        marketplace_id,
        store_id,
        sales_order_id,
        external_order_id,
        external_return_id,
        return_type,
        return_status,
        return_reason,
        return_initiator,
        return_requested_at,
        return_completed_at,
        currency_code,
        refund_amount,
        return_shipping_amount,
        source_file,
        source_sheet,
        source_row_number,
        raw_record_id,
        notes,
        updated_at
    )
    SELECT
        source_system,
        sales_channel_type,
        marketplace_id,
        store_id,
        sales_order_id,
        external_order_id,
        external_return_id,
        return_type,
        return_status,
        return_reason,
        return_initiator,
        return_requested_at::timestamptz,
        return_completed_at::timestamptz,
        currency_code,
        refund_amount::numeric,
        return_shipping_amount::numeric,
        source_file,
        source_sheet,
        source_row_number,
        raw_record_id,
        'Loaded by scripts/transform/sales_return.py',
        now()
    FROM return_rows
    ON CONFLICT (source_system, raw_record_id)
    DO UPDATE SET
        sales_order_id = COALESCE(EXCLUDED.sales_order_id, {target_schema}.fact_sales_return.sales_order_id),
        return_status = COALESCE(EXCLUDED.return_status, {target_schema}.fact_sales_return.return_status),
        return_reason = COALESCE(EXCLUDED.return_reason, {target_schema}.fact_sales_return.return_reason),
        return_initiator = COALESCE(EXCLUDED.return_initiator, {target_schema}.fact_sales_return.return_initiator),
        return_requested_at = COALESCE(EXCLUDED.return_requested_at, {target_schema}.fact_sales_return.return_requested_at),
        return_completed_at = COALESCE(EXCLUDED.return_completed_at, {target_schema}.fact_sales_return.return_completed_at),
        refund_amount = COALESCE(EXCLUDED.refund_amount, {target_schema}.fact_sales_return.refund_amount),
        return_shipping_amount = COALESCE(EXCLUDED.return_shipping_amount, {target_schema}.fact_sales_return.return_shipping_amount),
        source_file = EXCLUDED.source_file,
        source_sheet = EXCLUDED.source_sheet,
        source_row_number = EXCLUDED.source_row_number,
        notes = EXCLUDED.notes,
        updated_at = now()
    RETURNING source_system, raw_record_id, sales_return_id
),
available_returns AS (
    SELECT source_system, raw_record_id, sales_return_id
    FROM upserted_returns
    UNION ALL
    SELECT fsr.source_system, fsr.raw_record_id, fsr.sales_return_id
    FROM {target_schema}.fact_sales_return fsr
    JOIN return_rows rr
        ON rr.source_system = fsr.source_system
       AND rr.raw_record_id = fsr.raw_record_id
),
return_item_rows AS (
    SELECT DISTINCT ON (r.return_item_raw_record_id)
        ar.sales_return_id,
        oil.sales_order_item_id,
        r.product_id,
        r.product_sku_alias_id,
        r.source_line_id,
        r.source_sku_code,
        r.source_product_name,
        r.source_variation_name,
        r.return_qty,
        r.unit,
        r.refund_item_amount,
        r.item_status,
        r.source_file,
        r.source_sheet,
        r.source_row_number,
        r.return_item_raw_record_id AS raw_record_id,
        r.source_system
    FROM resolved_with_order r
    JOIN available_returns ar
        ON ar.source_system = r.source_system
       AND ar.raw_record_id = r.return_raw_record_id
    LEFT JOIN order_item_lookup oil
        ON oil.return_source_sequence = r.return_source_sequence
    WHERE r.store_id IS NOT NULL
      AND r.product_sku_alias_id IS NOT NULL
    ORDER BY r.return_item_raw_record_id, r.source_file DESC, r.source_row_number DESC
),
upserted_items AS (
    INSERT INTO {target_schema}.fact_sales_return_item (
        sales_return_id,
        source_system,
        sales_order_item_id,
        product_id,
        product_sku_alias_id,
        source_line_id,
        source_sku_code,
        source_product_name,
        source_variation_name,
        return_qty,
        unit,
        refund_item_amount,
        item_status,
        source_file,
        source_sheet,
        source_row_number,
        raw_record_id,
        notes,
        updated_at
    )
    SELECT
        sales_return_id,
        source_system,
        sales_order_item_id,
        product_id,
        product_sku_alias_id,
        source_line_id,
        source_sku_code,
        source_product_name,
        source_variation_name,
        return_qty::numeric,
        unit,
        refund_item_amount::numeric,
        item_status,
        source_file,
        source_sheet,
        source_row_number,
        raw_record_id,
        'Loaded by scripts/transform/sales_return.py',
        now()
    FROM return_item_rows
    ON CONFLICT (source_system, raw_record_id)
    DO UPDATE SET
        sales_return_id = EXCLUDED.sales_return_id,
        sales_order_item_id = COALESCE(EXCLUDED.sales_order_item_id, {target_schema}.fact_sales_return_item.sales_order_item_id),
        product_id = COALESCE(EXCLUDED.product_id, {target_schema}.fact_sales_return_item.product_id),
        product_sku_alias_id = COALESCE(EXCLUDED.product_sku_alias_id, {target_schema}.fact_sales_return_item.product_sku_alias_id),
        return_qty = COALESCE(EXCLUDED.return_qty, {target_schema}.fact_sales_return_item.return_qty),
        refund_item_amount = COALESCE(EXCLUDED.refund_item_amount, {target_schema}.fact_sales_return_item.refund_item_amount),
        item_status = COALESCE(EXCLUDED.item_status, {target_schema}.fact_sales_return_item.item_status),
        source_file = EXCLUDED.source_file,
        source_sheet = EXCLUDED.source_sheet,
        source_row_number = EXCLUDED.source_row_number,
        notes = EXCLUDED.notes,
        updated_at = now()
    RETURNING sales_return_item_id
)
SELECT
    (SELECT COUNT(*) FROM upserted_returns)::bigint AS return_rows,
    (SELECT COUNT(*) FROM upserted_items)::bigint AS return_item_rows;
