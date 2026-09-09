WITH source_fulfillment AS (
    SELECT *
    FROM {staging_schema}.sales_fulfillment_source
    WHERE fulfillment_source_sequence >= :batch_start
      AND fulfillment_source_sequence < :batch_end
),
source_info AS (
    SELECT source_system
    FROM source_fulfillment
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
resolved_rows AS (
    SELECT
        s.*,
        m.marketplace_id,
        sl.store_id
    FROM source_fulfillment s
    CROSS JOIN marketplace m
    LEFT JOIN store_lookup sl
        ON sl.lookup_store_name = s.normalized_store_name
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
fulfillment_rows AS (
    SELECT DISTINCT ON (r.raw_record_id)
        r.source_system,
        'online'::text AS sales_channel_type,
        r.marketplace_id,
        r.store_id,
        ol.sales_order_id,
        r.external_order_id,
        r.external_order_group_id,
        r.external_fulfillment_id,
        r.external_package_id,
        r.tracking_number,
        r.tracking_url,
        NULL::integer AS warehouse_id,
        r.source_warehouse_name,
        NULL::integer AS shipping_service_id,
        r.source_shipping_provider,
        r.source_shipping_service,
        r.source_shipping_service_level,
        r.fulfillment_status,
        r.logistics_status,
        r.handover_type,
        r.is_dropship,
        NULLIF(r.order_created_at_text, '')::timestamptz AS order_created_at,
        NULLIF(r.paid_at_text, '')::timestamptz AS paid_at,
        NULLIF(r.ready_to_ship_at_text, '')::timestamptz AS ready_to_ship_at,
        NULLIF(r.target_shipped_at_text, '')::timestamptz AS target_shipped_at,
        NULLIF(r.pickup_at_text, '')::timestamptz AS pickup_at,
        NULLIF(r.handover_at_text, '')::timestamptz AS handover_at,
        NULLIF(r.shipped_at_text, '')::timestamptz AS shipped_at,
        NULLIF(r.delivered_at_text, '')::timestamptz AS delivered_at,
        NULLIF(r.cancelled_at_text, '')::timestamptz AS cancelled_at,
        NULLIF(r.returned_at_text, '')::timestamptz AS returned_at,
        NULLIF(r.weight_kg, '')::numeric AS weight_kg,
        NULL::numeric AS package_length_cm,
        NULL::numeric AS package_width_cm,
        NULL::numeric AS package_height_cm,
        NULLIF(r.distance_fee_amount, '')::numeric AS distance_fee_amount,
        NULLIF(r.shipping_fee_amount, '')::numeric AS shipping_fee_amount,
        COALESCE(r.currency_code, 'IDR') AS currency_code,
        NULL::integer AS destination_location_id,
        r.destination_city,
        r.destination_province,
        r.destination_postal_code,
        r.destination_country,
        r.source_file,
        r.source_sheet,
        r.source_row_number,
        r.raw_record_id
    FROM resolved_rows r
    LEFT JOIN order_lookup ol
        ON ol.source_system = r.source_system
       AND ol.store_id = r.store_id
       AND ol.external_order_id = r.external_order_id
    WHERE r.store_id IS NOT NULL
    ORDER BY r.raw_record_id, r.data_completeness_score DESC, r.source_file DESC, r.source_row_number DESC
)
INSERT INTO {target_schema}.fact_sales_fulfillment (
    source_system,
    sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    external_order_id,
    external_order_group_id,
    external_fulfillment_id,
    external_package_id,
    tracking_number,
    tracking_url,
    warehouse_id,
    source_warehouse_name,
    shipping_service_id,
    source_shipping_provider,
    source_shipping_service,
    source_shipping_service_level,
    fulfillment_status,
    logistics_status,
    handover_type,
    is_dropship,
    order_created_at,
    paid_at,
    ready_to_ship_at,
    target_shipped_at,
    pickup_at,
    handover_at,
    shipped_at,
    delivered_at,
    cancelled_at,
    returned_at,
    weight_kg,
    package_length_cm,
    package_width_cm,
    package_height_cm,
    distance_fee_amount,
    shipping_fee_amount,
    currency_code,
    destination_location_id,
    destination_city,
    destination_province,
    destination_postal_code,
    destination_country,
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
    external_order_group_id,
    external_fulfillment_id,
    external_package_id,
    tracking_number,
    tracking_url,
    warehouse_id,
    source_warehouse_name,
    shipping_service_id,
    source_shipping_provider,
    source_shipping_service,
    source_shipping_service_level,
    fulfillment_status,
    logistics_status,
    handover_type,
    is_dropship,
    order_created_at,
    paid_at,
    ready_to_ship_at,
    target_shipped_at,
    pickup_at,
    handover_at,
    shipped_at,
    delivered_at,
    cancelled_at,
    returned_at,
    weight_kg,
    package_length_cm,
    package_width_cm,
    package_height_cm,
    distance_fee_amount,
    shipping_fee_amount,
    currency_code,
    destination_location_id,
    destination_city,
    destination_province,
    destination_postal_code,
    destination_country,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    'Loaded by scripts/transform/sales_fulfillment.py',
    now()
FROM fulfillment_rows
ON CONFLICT (source_system, raw_record_id)
DO UPDATE SET
    sales_order_id = COALESCE(EXCLUDED.sales_order_id, {target_schema}.fact_sales_fulfillment.sales_order_id),
    external_order_group_id = COALESCE(EXCLUDED.external_order_group_id, {target_schema}.fact_sales_fulfillment.external_order_group_id),
    external_package_id = COALESCE(EXCLUDED.external_package_id, {target_schema}.fact_sales_fulfillment.external_package_id),
    tracking_number = COALESCE(EXCLUDED.tracking_number, {target_schema}.fact_sales_fulfillment.tracking_number),
    tracking_url = COALESCE(EXCLUDED.tracking_url, {target_schema}.fact_sales_fulfillment.tracking_url),
    source_warehouse_name = COALESCE(EXCLUDED.source_warehouse_name, {target_schema}.fact_sales_fulfillment.source_warehouse_name),
    source_shipping_provider = COALESCE(EXCLUDED.source_shipping_provider, {target_schema}.fact_sales_fulfillment.source_shipping_provider),
    source_shipping_service = COALESCE(EXCLUDED.source_shipping_service, {target_schema}.fact_sales_fulfillment.source_shipping_service),
    source_shipping_service_level = COALESCE(EXCLUDED.source_shipping_service_level, {target_schema}.fact_sales_fulfillment.source_shipping_service_level),
    fulfillment_status = COALESCE(EXCLUDED.fulfillment_status, {target_schema}.fact_sales_fulfillment.fulfillment_status),
    logistics_status = COALESCE(EXCLUDED.logistics_status, {target_schema}.fact_sales_fulfillment.logistics_status),
    handover_type = COALESCE(EXCLUDED.handover_type, {target_schema}.fact_sales_fulfillment.handover_type),
    is_dropship = COALESCE(EXCLUDED.is_dropship, {target_schema}.fact_sales_fulfillment.is_dropship),
    order_created_at = COALESCE(EXCLUDED.order_created_at, {target_schema}.fact_sales_fulfillment.order_created_at),
    paid_at = COALESCE(EXCLUDED.paid_at, {target_schema}.fact_sales_fulfillment.paid_at),
    ready_to_ship_at = COALESCE(EXCLUDED.ready_to_ship_at, {target_schema}.fact_sales_fulfillment.ready_to_ship_at),
    target_shipped_at = COALESCE(EXCLUDED.target_shipped_at, {target_schema}.fact_sales_fulfillment.target_shipped_at),
    pickup_at = COALESCE(EXCLUDED.pickup_at, {target_schema}.fact_sales_fulfillment.pickup_at),
    handover_at = COALESCE(EXCLUDED.handover_at, {target_schema}.fact_sales_fulfillment.handover_at),
    shipped_at = COALESCE(EXCLUDED.shipped_at, {target_schema}.fact_sales_fulfillment.shipped_at),
    delivered_at = COALESCE(EXCLUDED.delivered_at, {target_schema}.fact_sales_fulfillment.delivered_at),
    cancelled_at = COALESCE(EXCLUDED.cancelled_at, {target_schema}.fact_sales_fulfillment.cancelled_at),
    returned_at = COALESCE(EXCLUDED.returned_at, {target_schema}.fact_sales_fulfillment.returned_at),
    weight_kg = COALESCE(EXCLUDED.weight_kg, {target_schema}.fact_sales_fulfillment.weight_kg),
    distance_fee_amount = COALESCE(EXCLUDED.distance_fee_amount, {target_schema}.fact_sales_fulfillment.distance_fee_amount),
    shipping_fee_amount = COALESCE(EXCLUDED.shipping_fee_amount, {target_schema}.fact_sales_fulfillment.shipping_fee_amount),
    destination_city = COALESCE(EXCLUDED.destination_city, {target_schema}.fact_sales_fulfillment.destination_city),
    destination_province = COALESCE(EXCLUDED.destination_province, {target_schema}.fact_sales_fulfillment.destination_province),
    destination_postal_code = COALESCE(EXCLUDED.destination_postal_code, {target_schema}.fact_sales_fulfillment.destination_postal_code),
    destination_country = COALESCE(EXCLUDED.destination_country, {target_schema}.fact_sales_fulfillment.destination_country),
    source_file = EXCLUDED.source_file,
    source_sheet = EXCLUDED.source_sheet,
    source_row_number = EXCLUDED.source_row_number,
    notes = EXCLUDED.notes,
    updated_at = now();
