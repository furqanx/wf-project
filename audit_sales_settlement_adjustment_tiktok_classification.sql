-- Validate whether unlinked TikTok/Tokopedia adjustment rows are non-order
-- GMV Ads costs rather than unresolved order/settlement adjustments.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

WITH adjustment AS (
    SELECT
        adjustment.*,
        fee_type.fee_code,
        fee_type.fee_name,
        CASE
            WHEN LOWER(COALESCE(adjustment.raw_transaction_type, ''))
                 LIKE '%gmv payment for tiktok ads%'
                THEN 'ads_cost'
            ELSE 'non_ads_adjustment'
        END AS governed_category,
        CASE
            WHEN adjustment.sales_order_id IS NOT NULL
              OR adjustment.sales_settlement_id IS NOT NULL
                THEN 'linked'
            ELSE 'unlinked'
        END AS linkage_status
    FROM public.fact_sales_settlement_adjustment adjustment
    JOIN public.fee_type fee_type
      ON fee_type.fee_type_id = adjustment.fee_type_id
    WHERE adjustment.is_active = TRUE
      AND adjustment.source_system = 'tiktok_tokopedia'
)
SELECT
    governed_category,
    linkage_status,
    fee_code,
    fee_name,
    raw_transaction_type,
    raw_adjustment_name,
    COUNT(*) AS adjustment_rows,
    COUNT(DISTINCT external_adjustment_id) AS external_adjustment_ids,
    COUNT(DISTINCT NULLIF(BTRIM(related_external_order_id), ''))
        AS related_order_ids,
    COUNT(*) FILTER (WHERE store_id IS NULL) AS rows_without_store,
    COUNT(*) FILTER (
        WHERE adjustment_occurred_at IS NULL
    ) AS rows_without_business_date,
    COUNT(*) FILTER (
        WHERE signed_adjustment_amount < 0
    ) AS negative_rows,
    COUNT(*) FILTER (
        WHERE signed_adjustment_amount > 0
    ) AS positive_rows,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount,
    MIN(adjustment_occurred_at) AS min_adjustment_at,
    MAX(adjustment_occurred_at) AS max_adjustment_at
FROM adjustment
GROUP BY
    governed_category,
    linkage_status,
    fee_code,
    fee_name,
    raw_transaction_type,
    raw_adjustment_name
ORDER BY adjustment_rows DESC, raw_transaction_type;

-- Related-order identity profile. Sentinel values must not be treated as IDs.
SELECT
    COALESCE(NULLIF(BTRIM(related_external_order_id), ''), '<NULL>')
        AS related_external_order_id,
    COUNT(*) AS adjustment_rows,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount
FROM public.fact_sales_settlement_adjustment
WHERE is_active = TRUE
  AND source_system = 'tiktok_tokopedia'
  AND sales_order_id IS NULL
  AND sales_settlement_id IS NULL
GROUP BY 1
ORDER BY adjustment_rows DESC, 1;

-- External adjustment IDs should be unique within each store. Any result here
-- requires review before publication at store/day or store/month grain.
SELECT
    store_id,
    external_adjustment_id,
    COUNT(*) AS adjustment_rows,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount
FROM public.fact_sales_settlement_adjustment
WHERE is_active = TRUE
  AND source_system = 'tiktok_tokopedia'
GROUP BY store_id, external_adjustment_id
HAVING COUNT(*) > 1
ORDER BY adjustment_rows DESC, store_id, external_adjustment_id;

-- Publication guardrails for treating unlinked GMV Ads rows as store-period
-- advertising cost. Every value should be zero.
WITH classified AS (
    SELECT
        adjustment.*,
        LOWER(COALESCE(adjustment.raw_transaction_type, ''))
            LIKE '%gmv payment for tiktok ads%' AS is_ads_cost
    FROM public.fact_sales_settlement_adjustment adjustment
    WHERE adjustment.is_active = TRUE
      AND adjustment.source_system = 'tiktok_tokopedia'
)
SELECT
    COUNT(*) FILTER (
        WHERE sales_order_id IS NULL
          AND sales_settlement_id IS NULL
          AND NOT is_ads_cost
    ) AS unlinked_non_ads_rows,
    COUNT(*) FILTER (
        WHERE is_ads_cost
          AND (sales_order_id IS NOT NULL OR sales_settlement_id IS NOT NULL)
    ) AS linked_ads_rows,
    COUNT(*) FILTER (
        WHERE is_ads_cost
          AND (store_id IS NULL OR adjustment_occurred_at IS NULL)
    ) AS ads_without_store_period_rows,
    COUNT(*) FILTER (
        WHERE is_ads_cost
          AND signed_adjustment_amount >= 0
    ) AS non_negative_ads_rows,
    COUNT(*) FILTER (
        WHERE is_ads_cost
          AND COALESCE(NULLIF(BTRIM(related_external_order_id), ''), '/')
              NOT IN ('/', '-', 'N/A', 'n/a')
    ) AS ads_with_real_related_order_id_rows
FROM classified;
