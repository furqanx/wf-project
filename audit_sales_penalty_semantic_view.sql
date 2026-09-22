-- Reconcile recognized penalty costs and enforce publication guardrails.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

SELECT
    source_system,
    penalty_category,
    attribution_grain,
    COUNT(*) AS penalty_rows,
    COUNT(*) FILTER (WHERE sales_order_id IS NOT NULL) AS linked_order_rows,
    COUNT(*) FILTER (
        WHERE sales_settlement_id IS NOT NULL
    ) AS linked_settlement_rows,
    SUM(signed_source_amount) AS signed_source_amount,
    SUM(recognized_penalty_cost_amount) AS recognized_penalty_cost_amount,
    MIN(penalty_date) AS min_penalty_date,
    MAX(penalty_date) AS max_penalty_date
FROM public.vw_sales_penalty_semantic
GROUP BY source_system, penalty_category, attribution_grain
ORDER BY source_system, attribution_grain;

-- Semantic totals must match the governed source populations exactly.
WITH source_totals AS (
    SELECT
        'lazada'::text AS source_system,
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
          )) = 'penalty'
      AND LOWER(REGEXP_REPLACE(
              TRIM(COALESCE(transaction_sub_type, '')),
              '[^a-zA-Z0-9]+',
              '_',
              'g'
          )) = 'penalty_deduction'
      AND movement_direction = 'debit'
      AND signed_amount < 0

    UNION ALL

    SELECT
        'tiktok_tokopedia'::text AS source_system,
        COUNT(*) AS source_rows,
        SUM(-governed_adjustment_amount) AS source_amount
    FROM public.vw_sales_settlement_adjustment_semantic
    WHERE source_system = 'tiktok_tokopedia'
      AND is_analytics_included
      AND governed_adjustment_category = 'penalty_cost'
      AND governed_adjustment_amount < 0
),
semantic_totals AS (
    SELECT
        source_system,
        COUNT(*) AS semantic_rows,
        SUM(recognized_penalty_cost_amount) AS semantic_amount
    FROM public.vw_sales_penalty_semantic
    GROUP BY source_system
)
SELECT
    COALESCE(source.source_system, semantic.source_system) AS source_system,
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
  ON semantic.source_system = source.source_system
ORDER BY source_system;

-- Every guardrail must be zero.
SELECT
    COUNT(*) FILTER (
        WHERE recognized_penalty_cost_amount <= 0
    ) AS non_positive_penalty_cost_rows,
    COUNT(*) FILTER (
        WHERE store_id IS NULL OR penalty_at IS NULL
    ) AS rows_without_store_period,
    COUNT(*) FILTER (
        WHERE source_system = 'lazada'
          AND (
              attribution_grain <> 'store_period'
              OR sales_order_id IS NOT NULL
              OR sales_settlement_id IS NOT NULL
          )
    ) AS invalid_lazada_attribution_rows,
    COUNT(*) FILTER (
        WHERE source_system = 'tiktok_tokopedia'
          AND (
              attribution_grain <> 'order'
              OR sales_order_id IS NULL
              OR sales_settlement_id IS NULL
          )
    ) AS invalid_tiktok_attribution_rows,
    COUNT(*) - COUNT(DISTINCT source_fact || ':' || source_record_id)
        AS duplicate_source_record_rows
FROM public.vw_sales_penalty_semantic;
