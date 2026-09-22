-- Validate Shopee wallet transactions as governed Ads Cost candidates.
-- Read-only: no production facts are updated.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_shopee_ads_candidate ON COMMIT DROP AS
SELECT
    balance.*,
    store.store_code,
    store.store_name,
    CASE
        WHEN balance.transaction_description_key =
             'isi_ulang_saldo_iklan_koin_penjual'
         AND balance.movement_direction = 'debit'
         AND balance.signed_amount < 0
            THEN 'ads_cost_debit'
        WHEN balance.transaction_description_key =
             'isi_ulang_saldo_iklan_koin_penjual'
         AND (
             balance.movement_direction = 'credit'
             OR balance.signed_amount > 0
         )
            THEN 'ads_cost_reversal'
        WHEN CONCAT_WS(
                 ' ',
                 balance.transaction_type,
                 balance.transaction_sub_type,
                 balance.transaction_description,
                 balance.transaction_description_key
             ) ~* '(iklan|ads?|advert)'
            THEN 'ads_keyword_other'
        ELSE 'not_ads'
    END AS ads_classification
FROM public.fact_balance_transaction balance
LEFT JOIN public.dim_store store
  ON store.store_id = balance.store_id
WHERE balance.is_active = TRUE
  AND balance.source_system = 'shopee'
  AND (
      balance.transaction_description_key =
          'isi_ulang_saldo_iklan_koin_penjual'
      OR CONCAT_WS(
             ' ',
             balance.transaction_type,
             balance.transaction_sub_type,
             balance.transaction_description,
             balance.transaction_description_key
         ) ~* '(iklan|ads?|advert)'
  );

CREATE INDEX ON tmp_shopee_ads_candidate (store_id, transaction_occurred_at);
CREATE INDEX ON tmp_shopee_ads_candidate (external_transaction_id);
ANALYZE tmp_shopee_ads_candidate;

-- A. Candidate semantics and source signs.
SELECT
    ads_classification,
    transaction_type,
    transaction_sub_type,
    transaction_status,
    transaction_description_key,
    movement_direction,
    COUNT(*) AS transaction_rows,
    COUNT(DISTINCT external_transaction_id) AS external_transaction_ids,
    COUNT(*) FILTER (WHERE store_id IS NULL) AS rows_without_store,
    COUNT(*) FILTER (
        WHERE transaction_occurred_at IS NULL
    ) AS rows_without_business_date,
    COUNT(*) FILTER (WHERE sales_order_id IS NOT NULL) AS linked_order_rows,
    COUNT(*) FILTER (
        WHERE sales_settlement_id IS NOT NULL
    ) AS linked_settlement_rows,
    SUM(signed_amount) AS signed_amount,
    SUM(
        CASE
            WHEN ads_classification = 'ads_cost_debit'
                THEN -signed_amount
            WHEN ads_classification = 'ads_cost_reversal'
                THEN -signed_amount
            ELSE 0
        END
    ) AS normalized_ads_cost_amount,
    MIN(transaction_occurred_at) AS min_transaction_at,
    MAX(transaction_occurred_at) AS max_transaction_at
FROM tmp_shopee_ads_candidate
GROUP BY
    ads_classification,
    transaction_type,
    transaction_sub_type,
    transaction_status,
    transaction_description_key,
    movement_direction
ORDER BY transaction_rows DESC, ads_classification;

-- B. Coverage by store and month.
SELECT
    DATE_TRUNC('month', transaction_occurred_at)::date AS transaction_month,
    store_id,
    store_code,
    store_name,
    ads_classification,
    COUNT(*) AS transaction_rows,
    SUM(signed_amount) AS signed_amount,
    SUM(-signed_amount) AS normalized_ads_cost_amount
FROM tmp_shopee_ads_candidate
WHERE ads_classification IN ('ads_cost_debit', 'ads_cost_reversal')
GROUP BY 1, 2, 3, 4, 5
ORDER BY 1, 3, 5;

-- C. Repeated external transaction IDs. Any result requires source review.
SELECT
    store_id,
    store_code,
    external_transaction_id,
    COUNT(*) AS transaction_rows,
    COUNT(DISTINCT signed_amount) AS distinct_amounts,
    MIN(transaction_occurred_at) AS min_transaction_at,
    MAX(transaction_occurred_at) AS max_transaction_at,
    SUM(signed_amount) AS signed_amount
FROM tmp_shopee_ads_candidate
WHERE external_transaction_id IS NOT NULL
  AND ads_classification IN ('ads_cost_debit', 'ads_cost_reversal')
GROUP BY store_id, store_code, external_transaction_id
HAVING COUNT(*) > 1
ORDER BY transaction_rows DESC, store_code, external_transaction_id;

-- D. Potential identity overlap with settlement adjustments. This should be
-- zero; wallet transaction IDs and adjustment IDs are separate domains.
SELECT
    COUNT(*) AS overlapping_rows,
    COUNT(DISTINCT balance.balance_transaction_id) AS balance_rows,
    COUNT(DISTINCT adjustment.sales_settlement_adjustment_id)
        AS adjustment_rows,
    SUM(balance.signed_amount) AS balance_signed_amount
FROM tmp_shopee_ads_candidate balance
JOIN public.fact_sales_settlement_adjustment adjustment
  ON adjustment.is_active = TRUE
 AND adjustment.source_system = balance.source_system
 AND adjustment.store_id = balance.store_id
 AND adjustment.external_adjustment_id = balance.external_transaction_id
WHERE balance.ads_classification IN ('ads_cost_debit', 'ads_cost_reversal');

-- E. Source-file coverage.
SELECT
    source_file,
    COUNT(*) AS transaction_rows,
    COUNT(DISTINCT store_id) AS stores,
    MIN(transaction_occurred_at) AS min_transaction_at,
    MAX(transaction_occurred_at) AS max_transaction_at,
    SUM(signed_amount) AS signed_amount
FROM tmp_shopee_ads_candidate
WHERE ads_classification IN ('ads_cost_debit', 'ads_cost_reversal')
GROUP BY source_file
ORDER BY min_transaction_at, source_file;

-- F. Strict publication guardrails. All values should be zero except
-- ads_keyword_other_rows, which must be reviewed and classified explicitly.
SELECT
    COUNT(*) FILTER (
        WHERE ads_classification = 'ads_cost_debit'
          AND (movement_direction <> 'debit' OR signed_amount >= 0)
    ) AS invalid_ads_debit_rows,
    COUNT(*) FILTER (
        WHERE ads_classification IN ('ads_cost_debit', 'ads_cost_reversal')
          AND (store_id IS NULL OR transaction_occurred_at IS NULL)
    ) AS ads_without_store_period_rows,
    COUNT(*) FILTER (
        WHERE ads_classification IN ('ads_cost_debit', 'ads_cost_reversal')
          AND (sales_order_id IS NOT NULL OR sales_settlement_id IS NOT NULL)
    ) AS ads_with_atomic_link_rows,
    COUNT(*) FILTER (
        WHERE ads_classification = 'ads_keyword_other'
    ) AS ads_keyword_other_rows
FROM tmp_shopee_ads_candidate;

ROLLBACK;
