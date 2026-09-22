-- Govern recognized marketplace penalty costs at their supported grain.

BEGIN;

DROP VIEW IF EXISTS public.vw_sales_penalty_semantic;

CREATE VIEW public.vw_sales_penalty_semantic AS
WITH lazada_penalty AS (
    SELECT
        balance.source_system,
        balance.marketplace_id,
        balance.store_id,
        NULL::bigint AS sales_order_id,
        NULL::bigint AS sales_settlement_id,
        balance.transaction_occurred_at AS penalty_at,
        balance.transaction_occurred_at::date AS penalty_date,
        'penalty_cost'::text AS penalty_category,
        'store_period'::text AS attribution_grain,
        'fact_balance_transaction'::text AS source_fact,
        balance.balance_transaction_id::text AS source_record_id,
        balance.external_transaction_id AS external_reference_id,
        balance.signed_amount AS signed_source_amount,
        -balance.signed_amount AS recognized_penalty_cost_amount,
        balance.transaction_description AS source_description,
        balance.transaction_description_key AS source_description_key,
        balance.source_file,
        balance.raw_record_id
    FROM public.fact_balance_transaction balance
    WHERE balance.is_active = TRUE
      AND balance.source_system = 'lazada'
      AND LOWER(REGEXP_REPLACE(
              TRIM(COALESCE(balance.transaction_type, '')),
              '[^a-zA-Z0-9]+',
              '_',
              'g'
          )) = 'penalty'
      AND LOWER(REGEXP_REPLACE(
              TRIM(COALESCE(balance.transaction_sub_type, '')),
              '[^a-zA-Z0-9]+',
              '_',
              'g'
          )) = 'penalty_deduction'
      AND balance.movement_direction = 'debit'
      AND balance.signed_amount < 0
),
tiktok_penalty AS (
    SELECT
        adjustment.source_system,
        adjustment.marketplace_id,
        adjustment.store_id,
        adjustment.resolved_sales_order_id AS sales_order_id,
        adjustment.sales_settlement_id,
        adjustment.adjustment_occurred_at AS penalty_at,
        adjustment.adjustment_occurred_at::date AS penalty_date,
        adjustment.governed_adjustment_category AS penalty_category,
        adjustment.governed_attribution_grain AS attribution_grain,
        'fact_sales_settlement_adjustment'::text AS source_fact,
        adjustment.sales_settlement_adjustment_id::text AS source_record_id,
        adjustment.external_adjustment_id AS external_reference_id,
        adjustment.signed_adjustment_amount AS signed_source_amount,
        -adjustment.governed_adjustment_amount
            AS recognized_penalty_cost_amount,
        adjustment.raw_transaction_type AS source_description,
        LOWER(REGEXP_REPLACE(
            TRIM(COALESCE(adjustment.raw_transaction_type, '')),
            '[^a-zA-Z0-9]+',
            '_',
            'g'
        )) AS source_description_key,
        adjustment.source_file,
        adjustment.raw_record_id
    FROM public.vw_sales_settlement_adjustment_semantic adjustment
    WHERE adjustment.source_system = 'tiktok_tokopedia'
      AND adjustment.is_analytics_included
      AND adjustment.governed_adjustment_category = 'penalty_cost'
      AND adjustment.governed_adjustment_amount < 0
)
SELECT * FROM lazada_penalty
UNION ALL
SELECT * FROM tiktok_penalty;

COMMENT ON VIEW public.vw_sales_penalty_semantic IS
'Governed recognized penalty costs using order grain where supported and store/period grain otherwise.';

COMMIT;
