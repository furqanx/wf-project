-- Final candidate audit for Shopee Ads Cost using explicit source semantics.
-- Avoid broad regex matching because order IDs can contain the substring "ad".

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_shopee_ads_governed ON COMMIT DROP AS
SELECT
    balance.*,
    store.store_code,
    store.store_name,
    CASE
        WHEN balance.transaction_description_key =
             'isi_ulang_saldo_iklan_koin_penjual'
         AND balance.movement_direction = 'debit'
         AND balance.signed_amount < 0
            THEN 'ads_cost'
        WHEN balance.transaction_description_key =
             'pengembalian_dana_atas_kelebihan_ppn_saldo_iklan_shopee'
         AND balance.movement_direction = 'credit'
         AND balance.signed_amount > 0
            THEN 'ads_cost_reversal'
        WHEN balance.transaction_description_key LIKE
             'pengembalian_dari_biaya_kampanye%'
          OR balance.transaction_description_key LIKE
             'penambahan_wallet_pengembalian_biaya_paket_campaign%'
            THEN 'campaign_marketing_reversal'
        ELSE 'excluded_non_ads'
    END AS governed_ads_category
FROM public.fact_balance_transaction balance
LEFT JOIN public.dim_store store
  ON store.store_id = balance.store_id
WHERE balance.is_active = TRUE
  AND balance.source_system = 'shopee';

CREATE INDEX ON tmp_shopee_ads_governed (
    governed_ads_category,
    store_id,
    transaction_occurred_at
);
ANALYZE tmp_shopee_ads_governed;

-- A. Governed candidate totals.
SELECT
    governed_ads_category,
    transaction_description_key,
    movement_direction,
    COUNT(*) AS transaction_rows,
    COUNT(DISTINCT external_transaction_id) AS external_transaction_ids,
    COUNT(*) FILTER (WHERE store_id IS NULL) AS rows_without_store,
    COUNT(*) FILTER (
        WHERE transaction_occurred_at IS NULL
    ) AS rows_without_business_date,
    SUM(signed_amount) AS signed_amount,
    SUM(-signed_amount) AS normalized_cost_amount,
    MIN(transaction_occurred_at) AS min_transaction_at,
    MAX(transaction_occurred_at) AS max_transaction_at
FROM tmp_shopee_ads_governed
WHERE governed_ads_category <> 'excluded_non_ads'
GROUP BY
    governed_ads_category,
    transaction_description_key,
    movement_direction
ORDER BY governed_ads_category, transaction_rows DESC;

-- B. Exact business-grain repetition. Because Shopee report rows do not expose
-- an external transaction ID, source file counts reveal overlapping exports.
WITH repeated AS (
    SELECT
        store_id,
        transaction_occurred_at,
        signed_amount,
        transaction_type,
        transaction_sub_type,
        transaction_status,
        transaction_description_key,
        COUNT(*) AS transaction_rows,
        COUNT(DISTINCT source_file) AS source_files
    FROM tmp_shopee_ads_governed
    WHERE governed_ads_category IN ('ads_cost', 'ads_cost_reversal')
    GROUP BY 1, 2, 3, 4, 5, 6, 7
    HAVING COUNT(*) > 1
)
SELECT
    COUNT(*) AS repeated_business_grains,
    COALESCE(SUM(transaction_rows - 1), 0) AS duplicate_extra_rows,
    COALESCE(SUM(transaction_rows - 1) FILTER (
        WHERE source_files > 1
    ), 0) AS cross_file_duplicate_extra_rows,
    COALESCE(SUM(ABS(signed_amount) * (transaction_rows - 1)), 0)
        AS duplicate_extra_amount
FROM repeated;

-- C. Detail for repeated business grains, if any.
SELECT
    store_id,
    store_code,
    transaction_occurred_at,
    signed_amount,
    transaction_description_key,
    COUNT(*) AS transaction_rows,
    COUNT(DISTINCT source_file) AS source_files,
    STRING_AGG(DISTINCT source_file, ' | ' ORDER BY source_file)
        AS source_file_list,
    MIN(balance_transaction_id) AS selected_balance_transaction_id
FROM tmp_shopee_ads_governed
WHERE governed_ads_category IN ('ads_cost', 'ads_cost_reversal')
GROUP BY
    store_id,
    store_code,
    transaction_occurred_at,
    signed_amount,
    transaction_description_key
HAVING COUNT(*) > 1
ORDER BY transaction_rows DESC, store_code, transaction_occurred_at
LIMIT 200;

-- D. Source coverage by store/month. `source_available_no_ads` is a legitimate
-- zero only when other wallet rows prove that the report source is available.
SELECT
    DATE_TRUNC('month', transaction_occurred_at)::date AS transaction_month,
    store_id,
    store_code,
    store_name,
    COUNT(*) AS wallet_rows,
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_cost'
    ) AS ads_debit_rows,
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_cost_reversal'
    ) AS ads_reversal_rows,
    SUM(-signed_amount) FILTER (
        WHERE governed_ads_category IN ('ads_cost', 'ads_cost_reversal')
    ) AS net_ads_cost_amount,
    CASE
        WHEN COUNT(*) FILTER (
                 WHERE governed_ads_category IN (
                     'ads_cost',
                     'ads_cost_reversal'
                 )
             ) > 0
            THEN 'source_available_with_ads'
        ELSE 'source_available_no_ads'
    END AS source_coverage_status
FROM tmp_shopee_ads_governed
WHERE transaction_occurred_at IS NOT NULL
GROUP BY 1, 2, 3, 4
ORDER BY 1, 3;

-- E. Publication guardrails excluding duplicate resolution, which is reported
-- separately above. Every value should be zero.
SELECT
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_cost'
          AND (movement_direction <> 'debit' OR signed_amount >= 0)
    ) AS invalid_ads_cost_rows,
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_cost_reversal'
          AND (movement_direction <> 'credit' OR signed_amount <= 0)
    ) AS invalid_ads_reversal_rows,
    COUNT(*) FILTER (
        WHERE governed_ads_category IN ('ads_cost', 'ads_cost_reversal')
          AND (store_id IS NULL OR transaction_occurred_at IS NULL)
    ) AS rows_without_store_period,
    COUNT(*) FILTER (
        WHERE governed_ads_category IN ('ads_cost', 'ads_cost_reversal')
          AND (sales_order_id IS NOT NULL OR sales_settlement_id IS NOT NULL)
    ) AS rows_with_atomic_link
FROM tmp_shopee_ads_governed;

ROLLBACK;
