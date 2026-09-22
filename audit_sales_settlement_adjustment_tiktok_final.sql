-- Final publication audit for governed TikTok/Tokopedia adjustments.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

SELECT
    governed_adjustment_category,
    governed_attribution_grain,
    COUNT(*) AS raw_adjustment_rows,
    COUNT(*) FILTER (WHERE is_analytics_included) AS included_adjustment_rows,
    COUNT(*) FILTER (WHERE NOT is_analytics_included) AS excluded_duplicate_rows,
    SUM(signed_adjustment_amount) AS raw_signed_adjustment_amount,
    SUM(governed_adjustment_amount) AS governed_adjustment_amount
FROM public.vw_sales_settlement_adjustment_semantic
WHERE source_system = 'tiktok_tokopedia'
GROUP BY governed_adjustment_category, governed_attribution_grain
ORDER BY governed_adjustment_category, governed_attribution_grain;

SELECT
    analytics_exclusion_reason,
    COUNT(*) AS excluded_rows,
    SUM(signed_adjustment_amount) AS excluded_signed_adjustment_amount
FROM public.vw_sales_settlement_adjustment_semantic
WHERE source_system = 'tiktok_tokopedia'
  AND NOT is_analytics_included
GROUP BY analytics_exclusion_reason
ORDER BY analytics_exclusion_reason;

-- Every publication guardrail must be zero.
WITH included_grain AS (
    SELECT
        source_system,
        store_id,
        external_adjustment_id,
        COALESCE(related_external_order_id, '') AS related_external_order_id,
        COALESCE(raw_transaction_type, '') AS raw_transaction_type,
        fee_type_id,
        signed_adjustment_amount,
        adjustment_occurred_at,
        COUNT(*) AS included_rows
    FROM public.vw_sales_settlement_adjustment_semantic
    WHERE source_system = 'tiktok_tokopedia'
      AND is_analytics_included
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
)
SELECT
    COUNT(*) FILTER (
        WHERE included_rows > 1
    ) AS repeated_included_business_grains,
    (
        SELECT COUNT(*)
        FROM public.vw_sales_settlement_adjustment_semantic
        WHERE source_system = 'tiktok_tokopedia'
          AND governed_attribution_grain = 'order'
          AND resolved_sales_order_id IS NULL
    ) AS order_attribution_without_order_rows,
    (
        SELECT COUNT(*)
        FROM public.vw_sales_settlement_adjustment_semantic
        WHERE source_system = 'tiktok_tokopedia'
          AND governed_attribution_grain = 'store_period'
          AND (store_id IS NULL OR adjustment_occurred_at IS NULL)
    ) AS invalid_store_period_rows,
    (
        SELECT COUNT(*)
        FROM public.vw_sales_settlement_adjustment_semantic
        WHERE source_system = 'tiktok_tokopedia'
          AND governed_attribution_grain = 'unresolved'
    ) AS unresolved_rows,
    (
        SELECT COUNT(*)
        FROM public.vw_sales_settlement_adjustment_semantic
        WHERE source_system = 'tiktok_tokopedia'
          AND related_external_order_id IN ('/', '-', 'N/A', 'n/a')
    ) AS remaining_related_order_sentinel_rows
FROM included_grain;
