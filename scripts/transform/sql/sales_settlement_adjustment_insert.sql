WITH source_adjustment AS (
    SELECT *
    FROM {staging_schema}.sales_settlement_adjustment_source
    WHERE adjustment_source_sequence >= :batch_start
      AND adjustment_source_sequence < :batch_end
),
source_info AS (
    SELECT source_system
    FROM source_adjustment
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
    FROM source_adjustment s
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
        ON r.related_external_order_id IS NOT NULL
       AND r.source_system = fso.source_system
       AND r.store_id = fso.store_id
       AND r.related_external_order_id = fso.external_order_id
    WHERE fso.sales_channel_type = 'online'
    ORDER BY fso.source_system, fso.store_id, fso.external_order_id, fso.sales_order_id
),
settlement_lookup AS (
    SELECT DISTINCT ON (
        fss.source_system,
        fss.store_id,
        fss.external_order_id
    )
        fss.source_system,
        fss.store_id,
        fss.external_order_id,
        fss.sales_settlement_id
    FROM {target_schema}.fact_sales_settlement fss
    JOIN resolved_rows r
        ON r.related_external_order_id IS NOT NULL
       AND r.source_system = fss.source_system
       AND r.store_id = fss.store_id
       AND r.related_external_order_id = fss.external_order_id
    WHERE fss.sales_channel_type = 'online'
    ORDER BY fss.source_system, fss.store_id, fss.external_order_id, fss.sales_settlement_id
),
adjustment_rows AS (
    SELECT
        r.*,
        ol.sales_order_id,
        sl.sales_settlement_id,
        CASE
            WHEN sl.sales_settlement_id IS NOT NULL THEN 'settlement_related'
            WHEN ol.sales_order_id IS NOT NULL THEN 'order_related'
            ELSE 'non_order_transaction'
        END AS adjustment_scope
    FROM resolved_rows r
    LEFT JOIN order_lookup ol
        ON ol.source_system = r.source_system
       AND ol.store_id = r.store_id
       AND ol.external_order_id = r.related_external_order_id
    LEFT JOIN settlement_lookup sl
        ON sl.source_system = r.source_system
       AND sl.store_id = r.store_id
       AND sl.external_order_id = r.related_external_order_id
)
INSERT INTO {target_schema}.fact_sales_settlement_adjustment (
    source_system,
    sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    sales_settlement_id,
    fee_type_id,
    external_adjustment_id,
    related_external_order_id,
    raw_transaction_type,
    adjustment_scope,
    raw_adjustment_name,
    raw_adjustment_amount,
    signed_adjustment_amount,
    amount_sign_from_source,
    sign_rule,
    sign_confidence,
    currency_code,
    adjustment_occurred_at,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    notes
)
SELECT
    source_system,
    'online' AS sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    sales_settlement_id,
    fee_type_id,
    external_adjustment_id,
    related_external_order_id,
    raw_transaction_type,
    adjustment_scope,
    raw_adjustment_name,
    raw_adjustment_amount::numeric,
    signed_adjustment_amount::numeric,
    amount_sign_from_source,
    sign_rule,
    sign_confidence,
    COALESCE(currency_code, 'IDR') AS currency_code,
    CASE
        WHEN adjustment_occurred_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN adjustment_occurred_at_text::timestamp
        WHEN adjustment_occurred_at_text ~ '^[0-9]{{4}}/[0-9]{{2}}/[0-9]{{2}}'
            THEN adjustment_occurred_at_text::timestamp
        WHEN adjustment_occurred_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}}$'
            THEN to_timestamp(adjustment_occurred_at_text, 'DD Mon YYYY')
        WHEN adjustment_occurred_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}'
            THEN to_timestamp(adjustment_occurred_at_text, 'DD Mon YYYY HH24:MI')
        ELSE NULL
    END AS adjustment_occurred_at,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    CONCAT_WS(
        '; ',
        'Loaded by scripts/transform/sales_adjustment_phase_4.py',
        'source_table=' || source_table,
        'transaction_type=' || raw_transaction_type,
        'phase4_label=' || phase4_label,
        'review_status=' || review_status
    ) AS notes
FROM adjustment_rows
WHERE store_id IS NOT NULL
ON CONFLICT DO NOTHING;
