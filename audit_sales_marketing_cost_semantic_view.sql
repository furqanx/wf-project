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

-- Every guardrail must be zero.
SELECT
    COUNT(*) FILTER (
        WHERE source_system = 'shopee'
          AND recognized_ads_cost_amount IS NOT NULL
    ) AS shopee_funding_published_as_ads_cost_rows,
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
