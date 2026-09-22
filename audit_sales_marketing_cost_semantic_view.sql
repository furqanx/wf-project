-- Reconcile governed marketing metrics and prevent funding from becoming cost.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

SELECT
    source_system,
    marketing_category,
    attribution_grain,
    COUNT(*) AS event_rows,
    SUM(signed_source_amount) AS signed_source_amount,
    SUM(ads_wallet_funding_amount) AS ads_wallet_funding_amount,
    SUM(recognized_ads_cost_amount) AS recognized_ads_cost_amount,
    SUM(recognized_campaign_marketing_cost_amount)
        AS recognized_campaign_marketing_cost_amount,
    MIN(event_date) AS min_event_date,
    MAX(event_date) AS max_event_date
FROM public.vw_sales_marketing_cost_semantic
GROUP BY source_system, marketing_category, attribution_grain
ORDER BY source_system, marketing_category;

-- Lazada semantic rows must reconcile exactly to the governed balance source.
WITH source_totals AS (
    SELECT
        CASE
            WHEN LOWER(REGEXP_REPLACE(
                     TRIM(COALESCE(transaction_sub_type, '')),
                     '[^a-zA-Z0-9]+',
                     '_',
                     'g'
                 )) = 'sponsored_solutions_top_up'
                THEN 'ads_wallet_funding'
            ELSE 'ads_cost'
        END AS marketing_category,
        COUNT(*) AS source_rows,
        SUM(-signed_amount) AS source_amount
    FROM public.fact_balance_transaction
    WHERE is_active = TRUE
      AND source_system = 'lazada'
      AND LOWER(REGEXP_REPLACE(
              TRIM(COALESCE(transaction_type, '')),
              '[^a-zA-Z0-9]+',
              '_',
              'g'
          )) = 'payment'
      AND LOWER(REGEXP_REPLACE(
              TRIM(COALESCE(transaction_sub_type, '')),
              '[^a-zA-Z0-9]+',
              '_',
              'g'
          )) IN (
              'sponsored_solutions_top_up',
              'sponsored_solution_spend'
          )
      AND movement_direction = 'debit'
      AND signed_amount < 0
    GROUP BY 1
),
semantic_totals AS (
    SELECT
        marketing_category,
        COUNT(*) AS semantic_rows,
        SUM(COALESCE(
            ads_wallet_funding_amount,
            recognized_ads_cost_amount
        )) AS semantic_amount
    FROM public.vw_sales_marketing_cost_semantic
    WHERE source_system = 'lazada'
    GROUP BY marketing_category
)
SELECT
    COALESCE(source.marketing_category, semantic.marketing_category)
        AS marketing_category,
    COALESCE(source.source_rows, 0) AS source_rows,
    COALESCE(semantic.semantic_rows, 0) AS semantic_rows,
    COALESCE(semantic.semantic_rows, 0) - COALESCE(source.source_rows, 0)
        AS row_delta,
    COALESCE(source.source_amount, 0) AS source_amount,
    COALESCE(semantic.semantic_amount, 0) AS semantic_amount,
    COALESCE(semantic.semantic_amount, 0)
        - COALESCE(source.source_amount, 0) AS amount_delta
FROM source_totals source
FULL JOIN semantic_totals semantic
  ON semantic.marketing_category = source.marketing_category
ORDER BY marketing_category;

-- Every guardrail must be zero.
SELECT
    COUNT(*) FILTER (
        WHERE source_system = 'shopee'
          AND recognized_ads_cost_amount IS NOT NULL
    ) AS shopee_funding_published_as_ads_cost_rows,
    COUNT(*) FILTER (
        WHERE source_system = 'lazada'
          AND marketing_category = 'ads_wallet_funding'
          AND recognized_ads_cost_amount IS NOT NULL
    ) AS lazada_funding_published_as_ads_cost_rows,
    COUNT(*) FILTER (
        WHERE source_system = 'lazada'
          AND marketing_category = 'ads_cost'
          AND ads_wallet_funding_amount IS NOT NULL
    ) AS lazada_ads_cost_published_as_funding_rows,
    COUNT(*) FILTER (
        WHERE marketing_category IN (
                  'ads_wallet_funding',
                  'ads_wallet_funding_reversal'
              )
          AND ads_wallet_funding_amount IS NULL
    ) AS funding_without_amount_rows,
    COUNT(*) FILTER (
        WHERE marketing_category = 'ads_cost'
          AND recognized_ads_cost_amount IS NULL
    ) AS ads_cost_without_amount_rows,
    COUNT(*) FILTER (
        WHERE marketing_category = 'campaign_marketing_cost'
          AND recognized_campaign_marketing_cost_amount IS NULL
    ) AS campaign_cost_without_amount_rows,
    COUNT(*) FILTER (
        WHERE store_id IS NULL OR event_at IS NULL
    ) AS rows_without_store_period,
    COUNT(*) - COUNT(DISTINCT source_fact || ':' || source_record_id)
        AS duplicate_source_record_rows
FROM public.vw_sales_marketing_cost_semantic;
