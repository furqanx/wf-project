-- Govern settlement adjustments by economic category and analytical grain.
-- Exact business duplicates remain in the raw fact but are excluded here.

BEGIN;

DROP VIEW IF EXISTS public.vw_sales_settlement_adjustment_semantic;

CREATE VIEW public.vw_sales_settlement_adjustment_semantic AS
WITH governed AS (
    SELECT
        adjustment.*,
        settlement.sales_order_id AS settlement_sales_order_id,
        COALESCE(
            adjustment.sales_order_id,
            settlement.sales_order_id
        ) AS resolved_sales_order_id,
        CASE
            WHEN adjustment.source_system = 'tiktok_tokopedia'
             AND (
                 LOWER(COALESCE(adjustment.raw_transaction_type, '')) LIKE
                     '%gmv payment for tiktok ads%'
                 OR LOWER(COALESCE(adjustment.raw_transaction_type, '')) LIKE
                     '%pembayaran gmv untuk iklan tiktok%'
                 OR LOWER(COALESCE(adjustment.raw_transaction_type, '')) LIKE
                     '%gmv payment for promote%'
             ) THEN 'ads_cost'
            WHEN adjustment.source_system = 'tiktok_tokopedia'
             AND LOWER(COALESCE(adjustment.raw_transaction_type, '')) LIKE
                 '%campaign package%'
                THEN 'campaign_marketing_cost'
            ELSE 'settlement_adjustment'
        END AS governed_adjustment_category,
        CASE
            WHEN COALESCE(
                     adjustment.sales_order_id,
                     settlement.sales_order_id
                 ) IS NOT NULL
                THEN 'order'
            WHEN adjustment.sales_settlement_id IS NOT NULL
                THEN 'settlement'
            WHEN adjustment.store_id IS NOT NULL
             AND adjustment.adjustment_occurred_at IS NOT NULL
                THEN 'store_period'
            ELSE 'unresolved'
        END AS governed_attribution_grain,
        ROW_NUMBER() OVER (
            PARTITION BY
                adjustment.source_system,
                adjustment.store_id,
                adjustment.external_adjustment_id,
                COALESCE(adjustment.related_external_order_id, ''),
                COALESCE(adjustment.raw_transaction_type, ''),
                adjustment.fee_type_id,
                adjustment.signed_adjustment_amount,
                adjustment.adjustment_occurred_at
            ORDER BY adjustment.sales_settlement_adjustment_id
        ) AS business_duplicate_rank
    FROM public.fact_sales_settlement_adjustment adjustment
    LEFT JOIN public.fact_sales_settlement settlement
      ON settlement.sales_settlement_id = adjustment.sales_settlement_id
    WHERE adjustment.is_active = TRUE
)
SELECT
    governed.*,
    business_duplicate_rank = 1 AS is_analytics_included,
    CASE
        WHEN business_duplicate_rank > 1 THEN 'duplicate_business_grain'
        ELSE NULL
    END AS analytics_exclusion_reason,
    CASE
        WHEN business_duplicate_rank = 1 THEN signed_adjustment_amount
        ELSE NULL
    END AS governed_adjustment_amount
FROM governed;

COMMENT ON VIEW public.vw_sales_settlement_adjustment_semantic IS
'Governed settlement adjustments with economic category, attribution grain, and non-destructive exact-duplicate exclusion.';

COMMIT;
