-- Audit Lazada advertising wallet funding and actual advertising spend.
-- Read-only: this script does not update production facts.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_lazada_ads_governed ON COMMIT DROP AS
SELECT
    balance.*,
    store.store_code,
    store.store_name,
    CASE
        WHEN balance.transaction_type = 'payment'
         AND balance.transaction_sub_type = 'sponsored_solutions_top_up'
            THEN 'ads_wallet_funding'
        WHEN balance.transaction_type = 'payment'
         AND balance.transaction_sub_type = 'sponsored_solution_spend'
            THEN 'ads_cost_candidate'
        WHEN CONCAT_WS(
                 ' ',
                 balance.transaction_type,
                 balance.transaction_sub_type,
                 balance.transaction_description,
                 balance.transaction_description_key
             ) ~* '(sponsor|advert|(^|[^a-z])ads?([^a-z]|$))'
            THEN 'ads_keyword_other'
        ELSE 'not_ads'
    END AS governed_ads_category
FROM public.fact_balance_transaction balance
LEFT JOIN public.dim_store store
  ON store.store_id = balance.store_id
WHERE balance.is_active = TRUE
  AND balance.source_system = 'lazada';

CREATE INDEX ON tmp_lazada_ads_governed (
    governed_ads_category,
    store_id,
    transaction_occurred_at
);
CREATE INDEX ON tmp_lazada_ads_governed (external_transaction_id);
ANALYZE tmp_lazada_ads_governed;

-- A. Exact source semantics, signs, linkage, and date range.
SELECT
    governed_ads_category,
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
    SUM(-signed_amount) AS normalized_positive_amount,
    MIN(transaction_occurred_at) AS min_transaction_at,
    MAX(transaction_occurred_at) AS max_transaction_at
FROM tmp_lazada_ads_governed
WHERE governed_ads_category <> 'not_ads'
GROUP BY
    governed_ads_category,
    transaction_type,
    transaction_sub_type,
    transaction_status,
    transaction_description_key,
    movement_direction
ORDER BY governed_ads_category, transaction_rows DESC;

-- B. Candidate detail. The small spend population must be inspected before
-- it can be published as recognized Ads Cost.
SELECT
    balance_transaction_id,
    store_id,
    store_code,
    store_name,
    transaction_occurred_at,
    external_transaction_id,
    transaction_type,
    transaction_sub_type,
    transaction_status,
    transaction_description,
    transaction_description_key,
    movement_direction,
    signed_amount,
    sales_order_id,
    sales_settlement_id,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id
FROM tmp_lazada_ads_governed
WHERE governed_ads_category IN (
    'ads_cost_candidate',
    'ads_keyword_other'
)
ORDER BY
    governed_ads_category,
    transaction_occurred_at,
    balance_transaction_id;

-- C. Store/month coverage. Funding and spend are deliberately reported in
-- separate columns; funding must never be treated as recognized expense.
SELECT
    DATE_TRUNC('month', transaction_occurred_at)::date AS transaction_month,
    store_id,
    store_code,
    store_name,
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_wallet_funding'
    ) AS funding_rows,
    SUM(-signed_amount) FILTER (
        WHERE governed_ads_category = 'ads_wallet_funding'
    ) AS wallet_funding_amount,
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_cost_candidate'
    ) AS spend_rows,
    SUM(-signed_amount) FILTER (
        WHERE governed_ads_category = 'ads_cost_candidate'
    ) AS candidate_ads_cost_amount,
    CASE
        WHEN COUNT(*) FILTER (
                 WHERE governed_ads_category = 'ads_cost_candidate'
             ) > 0
            THEN 'actual_spend_available'
        WHEN COUNT(*) FILTER (
                 WHERE governed_ads_category = 'ads_wallet_funding'
             ) > 0
            THEN 'funding_only_ads_cost_unknown'
        ELSE 'no_ads_source_row'
    END AS ads_source_status
FROM tmp_lazada_ads_governed
WHERE governed_ads_category IN (
    'ads_wallet_funding',
    'ads_cost_candidate'
)
  AND transaction_occurred_at IS NOT NULL
GROUP BY 1, 2, 3, 4
ORDER BY 1, 3;

-- D. Source-file coverage by semantic category.
SELECT
    governed_ads_category,
    source_file,
    COUNT(*) AS transaction_rows,
    COUNT(DISTINCT store_id) AS stores,
    COUNT(DISTINCT DATE_TRUNC('month', transaction_occurred_at)) AS months,
    MIN(transaction_occurred_at) AS min_transaction_at,
    MAX(transaction_occurred_at) AS max_transaction_at,
    SUM(signed_amount) AS signed_amount
FROM tmp_lazada_ads_governed
WHERE governed_ads_category IN (
    'ads_wallet_funding',
    'ads_cost_candidate'
)
GROUP BY governed_ads_category, source_file
ORDER BY governed_ads_category, min_transaction_at, source_file;

-- E. Repeated external IDs. The identity may legitimately repeat only when
-- the source proves that it represents distinct movements.
SELECT
    governed_ads_category,
    store_id,
    store_code,
    external_transaction_id,
    COUNT(*) AS transaction_rows,
    COUNT(DISTINCT signed_amount) AS distinct_amounts,
    COUNT(DISTINCT source_file) AS source_files,
    MIN(transaction_occurred_at) AS min_transaction_at,
    MAX(transaction_occurred_at) AS max_transaction_at,
    SUM(signed_amount) AS signed_amount
FROM tmp_lazada_ads_governed
WHERE governed_ads_category IN (
    'ads_wallet_funding',
    'ads_cost_candidate'
)
  AND external_transaction_id IS NOT NULL
GROUP BY
    governed_ads_category,
    store_id,
    store_code,
    external_transaction_id
HAVING COUNT(*) > 1
ORDER BY transaction_rows DESC, store_code, external_transaction_id;

-- F. Exact repeated business grains, including overlapping source exports.
WITH repeated AS (
    SELECT
        governed_ads_category,
        store_id,
        transaction_occurred_at,
        external_transaction_id,
        signed_amount,
        transaction_type,
        transaction_sub_type,
        transaction_status,
        transaction_description_key,
        COUNT(*) AS transaction_rows,
        COUNT(DISTINCT source_file) AS source_files
    FROM tmp_lazada_ads_governed
    WHERE governed_ads_category IN (
        'ads_wallet_funding',
        'ads_cost_candidate'
    )
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
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

-- G. Potential overlap with governed settlement adjustments. Balance wallet
-- activity and settlement adjustments are separate source domains.
SELECT
    COUNT(*) AS overlapping_rows,
    COUNT(DISTINCT balance.balance_transaction_id) AS balance_rows,
    COUNT(DISTINCT adjustment.sales_settlement_adjustment_id)
        AS adjustment_rows,
    SUM(balance.signed_amount) AS balance_signed_amount
FROM tmp_lazada_ads_governed balance
JOIN public.fact_sales_settlement_adjustment adjustment
  ON adjustment.is_active = TRUE
 AND adjustment.source_system = balance.source_system
 AND adjustment.store_id = balance.store_id
 AND adjustment.external_adjustment_id = balance.external_transaction_id
WHERE balance.governed_ads_category IN (
    'ads_wallet_funding',
    'ads_cost_candidate'
);

-- H. Publication guardrails. All values should be zero. A non-zero keyword
-- count means an additional source description requires classification.
SELECT
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_wallet_funding'
          AND (movement_direction <> 'debit' OR signed_amount >= 0)
    ) AS invalid_funding_sign_rows,
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_cost_candidate'
          AND (movement_direction <> 'debit' OR signed_amount >= 0)
    ) AS invalid_spend_sign_rows,
    COUNT(*) FILTER (
        WHERE governed_ads_category IN (
                  'ads_wallet_funding',
                  'ads_cost_candidate'
              )
          AND (store_id IS NULL OR transaction_occurred_at IS NULL)
    ) AS rows_without_store_period,
    COUNT(*) FILTER (
        WHERE governed_ads_category IN (
                  'ads_wallet_funding',
                  'ads_cost_candidate'
              )
          AND (sales_order_id IS NOT NULL OR sales_settlement_id IS NOT NULL)
    ) AS rows_with_atomic_link,
    COUNT(*) FILTER (
        WHERE governed_ads_category = 'ads_keyword_other'
    ) AS unclassified_ads_keyword_rows
FROM tmp_lazada_ads_governed;

ROLLBACK;
