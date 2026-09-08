WITH source_balance AS (
    SELECT *
    FROM {staging_schema}.sales_balance_transaction_source
    WHERE balance_source_sequence >= :batch_start
      AND balance_source_sequence < :batch_end
),
source_info AS (
    SELECT source_system
    FROM source_balance
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
    FROM source_balance s
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
        ON r.external_order_id IS NOT NULL
       AND r.source_system = fso.source_system
       AND r.store_id = fso.store_id
       AND r.external_order_id = fso.external_order_id
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
        ON r.external_order_id IS NOT NULL
       AND r.source_system = fss.source_system
       AND r.store_id = fss.store_id
       AND r.external_order_id = fss.external_order_id
    WHERE fss.sales_channel_type = 'online'
    ORDER BY fss.source_system, fss.store_id, fss.external_order_id, fss.sales_settlement_id
),
balance_rows AS (
    SELECT
        r.*,
        ol.sales_order_id,
        sl.sales_settlement_id
    FROM resolved_rows r
    LEFT JOIN order_lookup ol
        ON ol.source_system = r.source_system
       AND ol.store_id = r.store_id
       AND ol.external_order_id = r.external_order_id
    LEFT JOIN settlement_lookup sl
        ON sl.source_system = r.source_system
       AND sl.store_id = r.store_id
       AND sl.external_order_id = r.external_order_id
)
INSERT INTO {target_schema}.fact_balance_transaction (
    source_system,
    sales_channel_type,
    marketplace_id,
    store_id,
    sales_order_id,
    sales_settlement_id,
    external_transaction_id,
    external_order_id,
    transaction_type,
    transaction_sub_type,
    transaction_status,
    transaction_description,
    transaction_description_key,
    movement_direction,
    raw_amount,
    signed_amount,
    amount_sign_from_source,
    balance_after_amount,
    currency_code,
    transaction_occurred_at,
    transaction_requested_at,
    transaction_succeeded_at,
    bank_account,
    source_table,
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
    external_transaction_id,
    external_order_id,
    transaction_type,
    transaction_sub_type,
    transaction_status,
    transaction_description,
    transaction_description_key,
    movement_direction,
    raw_amount::numeric,
    signed_amount::numeric,
    amount_sign_from_source::integer,
    NULLIF(balance_after_amount, '')::numeric,
    COALESCE(currency_code, 'IDR') AS currency_code,
    CASE
        WHEN transaction_occurred_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN transaction_occurred_at_text::timestamp
        WHEN transaction_occurred_at_text ~ '^[0-9]{{4}}/[0-9]{{2}}/[0-9]{{2}}'
            THEN transaction_occurred_at_text::timestamp
        WHEN transaction_occurred_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}'
            THEN to_timestamp(transaction_occurred_at_text, 'DD Mon YYYY HH24:MI:SS')
        WHEN transaction_occurred_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}'
            THEN to_timestamp(transaction_occurred_at_text, 'DD Mon YYYY HH24:MI')
        WHEN transaction_occurred_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}}$'
            THEN to_timestamp(transaction_occurred_at_text, 'DD Mon YYYY')
        ELSE NULL
    END AS transaction_occurred_at,
    CASE
        WHEN transaction_requested_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN transaction_requested_at_text::timestamp
        WHEN transaction_requested_at_text ~ '^[0-9]{{4}}/[0-9]{{2}}/[0-9]{{2}}'
            THEN transaction_requested_at_text::timestamp
        WHEN transaction_requested_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}'
            THEN to_timestamp(transaction_requested_at_text, 'DD Mon YYYY HH24:MI:SS')
        WHEN transaction_requested_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}'
            THEN to_timestamp(transaction_requested_at_text, 'DD Mon YYYY HH24:MI')
        WHEN transaction_requested_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}}$'
            THEN to_timestamp(transaction_requested_at_text, 'DD Mon YYYY')
        ELSE NULL
    END AS transaction_requested_at,
    CASE
        WHEN transaction_succeeded_at_text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
            THEN transaction_succeeded_at_text::timestamp
        WHEN transaction_succeeded_at_text ~ '^[0-9]{{4}}/[0-9]{{2}}/[0-9]{{2}}'
            THEN transaction_succeeded_at_text::timestamp
        WHEN transaction_succeeded_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}'
            THEN to_timestamp(transaction_succeeded_at_text, 'DD Mon YYYY HH24:MI:SS')
        WHEN transaction_succeeded_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}} [0-9]{{2}}:[0-9]{{2}}'
            THEN to_timestamp(transaction_succeeded_at_text, 'DD Mon YYYY HH24:MI')
        WHEN transaction_succeeded_at_text ~ '^[0-9]{{2}} [A-Za-z]{{3}} [0-9]{{4}}$'
            THEN to_timestamp(transaction_succeeded_at_text, 'DD Mon YYYY')
        ELSE NULL
    END AS transaction_succeeded_at,
    bank_account,
    source_table,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    CONCAT_WS(
        '; ',
        'Loaded by scripts/transform/sales_balance_phase_5.py',
        'source_table=' || source_table,
        'transaction_type=' || transaction_type,
        'transaction_sub_type=' || COALESCE(transaction_sub_type, ''),
        'transaction_status=' || COALESCE(transaction_status, '')
    ) AS notes
FROM balance_rows
WHERE store_id IS NOT NULL
ON CONFLICT DO NOTHING;
