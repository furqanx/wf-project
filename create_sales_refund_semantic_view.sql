-- Govern completed-return monetary values without treating unknown as zero.

BEGIN;

CREATE OR REPLACE VIEW public.vw_sales_refund_semantic AS
WITH order_resolution AS (
    SELECT
        candidate.sales_order_id AS source_sales_order_id,
        canonical.sales_order_id AS canonical_sales_order_id
    FROM public.vw_sales_order_channel_classification candidate
    JOIN public.vw_sales_order_channel_classification canonical
      ON canonical.source_system = candidate.source_system
     AND canonical.external_order_id = candidate.external_order_id
     AND COALESCE(canonical.net_order_amount, 0) =
         COALESCE(candidate.net_order_amount, 0)
     AND canonical.product_quantity_signature =
         candidate.product_quantity_signature
     AND canonical.is_analytics_included = TRUE
    WHERE candidate.source_system IN (
        'shopee',
        'lazada',
        'tiktok_tokopedia'
    )
),
completed_return AS (
    SELECT
        resolution.canonical_sales_order_id AS sales_order_id,
        returns.source_system,
        returns.external_order_id,
        COUNT(*) AS completed_return_count,
        SUM(COALESCE(returns.refund_amount, 0))
            AS completed_header_refund_amount,
        MIN(returns.return_requested_at) AS first_return_requested_at,
        MAX(returns.return_completed_at) AS last_return_completed_at
    FROM public.fact_sales_return returns
    JOIN order_resolution resolution
      ON resolution.source_sales_order_id = returns.sales_order_id
    WHERE returns.is_active = TRUE
      AND returns.return_type <> 'cancellation'
      AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE '%dibatalkan%'
      AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE '%batal%'
      AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE '%diproses%'
      AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE 'in transit:%'
      AND (
            returns.return_completed_at IS NOT NULL
         OR LOWER(COALESCE(returns.return_status, '')) = 'selesai'
      )
    GROUP BY
        resolution.canonical_sales_order_id,
        returns.source_system,
        returns.external_order_id
),
shopee_settlement_refund AS (
    SELECT
        external_order_id,
        SUM(-refund_amount) AS refund_amount
    FROM public.fact_sales_settlement
    WHERE is_active = TRUE
      AND source_system = 'shopee'
      AND refund_amount < 0
    GROUP BY external_order_id
)
SELECT
    completed.sales_order_id,
    completed.source_system,
    completed.external_order_id,
    completed.completed_return_count,
    CASE
        WHEN completed.source_system = 'shopee'
            THEN 'settlement_header'
        WHEN completed.source_system = 'tiktok_tokopedia'
            THEN 'return_header'
        ELSE NULL
    END AS refund_value_source,
    CASE
        WHEN completed.source_system = 'shopee'
         AND shopee.refund_amount IS NOT NULL
            THEN 'recognized'
        WHEN completed.source_system = 'tiktok_tokopedia'
         AND completed.completed_header_refund_amount > 0
            THEN 'recognized'
        ELSE 'monetary_value_unknown'
    END AS refund_value_status,
    CASE
        WHEN completed.source_system = 'shopee'
            THEN shopee.refund_amount
        WHEN completed.source_system = 'tiktok_tokopedia'
         AND completed.completed_header_refund_amount > 0
            THEN completed.completed_header_refund_amount
        ELSE NULL
    END AS recognized_refund_amount,
    completed.first_return_requested_at,
    completed.last_return_completed_at
FROM completed_return completed
LEFT JOIN shopee_settlement_refund shopee
  ON completed.source_system = 'shopee'
 AND shopee.external_order_id = completed.external_order_id;

COMMENT ON VIEW public.vw_sales_refund_semantic IS
'Completed-return refund values using TikTok/Tokopedia return headers and Shopee settlement headers; missing monetary values remain unknown.';

COMMIT;
