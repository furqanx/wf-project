-- Marketing cash-flow and recognized-cost semantic layer.
-- Funding is intentionally separate from recognized expense.

BEGIN;

DROP VIEW IF EXISTS public.vw_sales_marketing_cost_semantic;

CREATE VIEW public.vw_sales_marketing_cost_semantic AS
WITH shopee_wallet AS (
    SELECT
        balance.source_system,
        balance.marketplace_id,
        balance.store_id,
        balance.transaction_occurred_at AS event_at,
        balance.transaction_occurred_at::date AS event_date,
        CASE
            WHEN balance.transaction_description_key =
                 'isi_ulang_saldo_iklan_koin_penjual'
             AND balance.movement_direction = 'debit'
             AND balance.signed_amount < 0
                THEN 'ads_wallet_funding'
            WHEN balance.transaction_description_key =
                 'pengembalian_dana_atas_kelebihan_ppn_saldo_iklan_shopee'
             AND balance.movement_direction = 'credit'
             AND balance.signed_amount > 0
                THEN 'ads_wallet_funding_reversal'
            ELSE 'campaign_marketing_reversal'
        END AS marketing_category,
        'store_period'::text AS attribution_grain,
        'fact_balance_transaction'::text AS source_fact,
        balance.balance_transaction_id::text AS source_record_id,
        balance.signed_amount AS signed_source_amount,
        CASE
            WHEN balance.transaction_description_key =
                 'isi_ulang_saldo_iklan_koin_penjual'
                THEN -balance.signed_amount
            WHEN balance.transaction_description_key =
                 'pengembalian_dana_atas_kelebihan_ppn_saldo_iklan_shopee'
                THEN -balance.signed_amount
            ELSE NULL
        END AS ads_wallet_funding_amount,
        NULL::numeric AS recognized_ads_cost_amount,
        CASE
            WHEN balance.transaction_description_key LIKE
                 'pengembalian_dari_biaya_kampanye%'
              OR balance.transaction_description_key LIKE
                 'penambahan_wallet_pengembalian_biaya_paket_campaign%'
                THEN -balance.signed_amount
            ELSE NULL
        END AS recognized_campaign_marketing_cost_amount,
        balance.transaction_description AS source_description,
        balance.transaction_description_key AS source_description_key,
        balance.source_file,
        balance.raw_record_id
    FROM public.fact_balance_transaction balance
    WHERE balance.is_active = TRUE
      AND balance.source_system = 'shopee'
      AND (
          (
              balance.transaction_description_key =
                  'isi_ulang_saldo_iklan_koin_penjual'
              AND balance.movement_direction = 'debit'
              AND balance.signed_amount < 0
          )
          OR (
              balance.transaction_description_key =
                  'pengembalian_dana_atas_kelebihan_ppn_saldo_iklan_shopee'
              AND balance.movement_direction = 'credit'
              AND balance.signed_amount > 0
          )
          OR balance.transaction_description_key LIKE
              'pengembalian_dari_biaya_kampanye%'
          OR balance.transaction_description_key LIKE
              'penambahan_wallet_pengembalian_biaya_paket_campaign%'
      )
),
lazada_marketing AS (
    SELECT
        balance.source_system,
        balance.marketplace_id,
        balance.store_id,
        balance.transaction_occurred_at AS event_at,
        balance.transaction_occurred_at::date AS event_date,
        CASE
            WHEN normalized.normalized_transaction_sub_type =
                 'sponsored_solutions_top_up'
                THEN 'ads_wallet_funding'
            ELSE 'ads_cost'
        END AS marketing_category,
        'store_period'::text AS attribution_grain,
        'fact_balance_transaction'::text AS source_fact,
        balance.balance_transaction_id::text AS source_record_id,
        balance.signed_amount AS signed_source_amount,
        CASE
            WHEN normalized.normalized_transaction_sub_type =
                 'sponsored_solutions_top_up'
                THEN -balance.signed_amount
            ELSE NULL
        END AS ads_wallet_funding_amount,
        CASE
            WHEN normalized.normalized_transaction_sub_type =
                 'sponsored_solution_spend'
                THEN -balance.signed_amount
            ELSE NULL
        END AS recognized_ads_cost_amount,
        NULL::numeric AS recognized_campaign_marketing_cost_amount,
        balance.transaction_description AS source_description,
        balance.transaction_description_key AS source_description_key,
        balance.source_file,
        balance.raw_record_id
    FROM public.fact_balance_transaction balance
    CROSS JOIN LATERAL (
        SELECT LOWER(REGEXP_REPLACE(
            TRIM(COALESCE(balance.transaction_sub_type, '')),
            '[^a-zA-Z0-9]+',
            '_',
            'g'
        )) AS normalized_transaction_sub_type
    ) normalized
    WHERE balance.is_active = TRUE
      AND balance.source_system = 'lazada'
      AND LOWER(REGEXP_REPLACE(
              TRIM(COALESCE(balance.transaction_type, '')),
              '[^a-zA-Z0-9]+',
              '_',
              'g'
          )) = 'payment'
      AND normalized.normalized_transaction_sub_type IN (
          'sponsored_solutions_top_up',
          'sponsored_solution_spend'
      )
      AND balance.movement_direction = 'debit'
      AND balance.signed_amount < 0
),
tiktok_cost AS (
    SELECT
        adjustment.source_system,
        adjustment.marketplace_id,
        adjustment.store_id,
        adjustment.adjustment_occurred_at AS event_at,
        adjustment.adjustment_occurred_at::date AS event_date,
        adjustment.governed_adjustment_category AS marketing_category,
        adjustment.governed_attribution_grain AS attribution_grain,
        'fact_sales_settlement_adjustment'::text AS source_fact,
        adjustment.sales_settlement_adjustment_id::text AS source_record_id,
        adjustment.signed_adjustment_amount AS signed_source_amount,
        NULL::numeric AS ads_wallet_funding_amount,
        CASE
            WHEN adjustment.governed_adjustment_category = 'ads_cost'
                THEN -adjustment.governed_adjustment_amount
            ELSE NULL
        END AS recognized_ads_cost_amount,
        CASE
            WHEN adjustment.governed_adjustment_category =
                 'campaign_marketing_cost'
                THEN -adjustment.governed_adjustment_amount
            ELSE NULL
        END AS recognized_campaign_marketing_cost_amount,
        adjustment.raw_transaction_type AS source_description,
        LOWER(REGEXP_REPLACE(
            adjustment.raw_transaction_type,
            '[^a-zA-Z0-9]+',
            '_',
            'g'
        )) AS source_description_key,
        adjustment.source_file,
        adjustment.raw_record_id
    FROM public.vw_sales_settlement_adjustment_semantic adjustment
    WHERE adjustment.source_system = 'tiktok_tokopedia'
      AND adjustment.is_analytics_included
      AND adjustment.governed_adjustment_category IN (
          'ads_cost',
          'campaign_marketing_cost'
      )
)
SELECT * FROM shopee_wallet
UNION ALL
SELECT * FROM lazada_marketing
UNION ALL
SELECT * FROM tiktok_cost;

COMMENT ON VIEW public.vw_sales_marketing_cost_semantic IS
'Governed marketing events separating wallet funding from recognized Ads and Campaign Marketing Cost.';

COMMIT;
