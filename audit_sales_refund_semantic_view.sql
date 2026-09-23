-- Reconcile governed refund values and sales semantic propagation.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

SELECT
    source_system,
    refund_value_source,
    refund_value_status,
    COUNT(*) AS completed_return_orders,
    SUM(completed_return_count) AS completed_return_events,
    COUNT(*) FILTER (
        WHERE recognized_refund_amount IS NOT NULL
    ) AS orders_with_refund_value,
    SUM(recognized_refund_amount) AS recognized_refund_amount,
    MIN(first_return_requested_at) AS min_return_requested_at,
    MAX(last_return_completed_at) AS max_return_completed_at
FROM public.vw_sales_refund_semantic
GROUP BY source_system, refund_value_source, refund_value_status
ORDER BY source_system, refund_value_status;

-- Expected governed source totals must reconcile exactly.
WITH expected AS (
    SELECT
        'shopee'::text AS source_system,
        COUNT(*) AS expected_orders,
        SUM(settlement_refund.refund_amount) AS expected_amount
    FROM public.vw_sales_refund_semantic semantic
    JOIN (
        SELECT
            external_order_id,
            SUM(-refund_amount) AS refund_amount
        FROM public.fact_sales_settlement
        WHERE is_active = TRUE
          AND source_system = 'shopee'
          AND refund_amount < 0
        GROUP BY external_order_id
    ) settlement_refund
      ON settlement_refund.external_order_id = semantic.external_order_id
    WHERE semantic.source_system = 'shopee'
      AND semantic.refund_value_status = 'recognized'

    UNION ALL

    SELECT
        'tiktok_tokopedia'::text AS source_system,
        COUNT(*) AS expected_orders,
        SUM(recognized_refund_amount) AS expected_amount
    FROM public.vw_sales_refund_semantic
    WHERE source_system = 'tiktok_tokopedia'
      AND refund_value_status = 'recognized'
),
actual AS (
    SELECT
        source_system,
        COUNT(*) FILTER (
            WHERE refund_value_status = 'recognized'
        ) AS actual_orders,
        SUM(recognized_refund_amount) AS actual_amount
    FROM public.vw_sales_refund_semantic
    GROUP BY source_system
)
SELECT
    expected.source_system,
    expected.expected_orders,
    actual.actual_orders,
    actual.actual_orders - expected.expected_orders AS order_delta,
    expected.expected_amount,
    actual.actual_amount,
    actual.actual_amount - expected.expected_amount AS amount_delta
FROM expected
JOIN actual
  ON actual.source_system = expected.source_system
ORDER BY expected.source_system;

-- Sales semantic layer must publish the same recognized refund total.
SELECT
    refund.source_system,
    refund.refund_orders,
    sales.completed_return_orders,
    refund.refund_amount,
    sales.refund_amount AS sales_refund_amount,
    sales.refund_amount - refund.refund_amount AS amount_delta
FROM (
    SELECT
        source_system,
        COUNT(*) FILTER (
            WHERE refund_value_status = 'recognized'
        ) AS refund_orders,
        COALESCE(SUM(recognized_refund_amount), 0) AS refund_amount
    FROM public.vw_sales_refund_semantic
    GROUP BY source_system
) refund
JOIN (
    SELECT
        source_system,
        SUM(completed_return_order_count) AS completed_return_orders,
        SUM(recognized_refund_amount) AS refund_amount
    FROM public.vw_sales_semantic_order
    GROUP BY source_system
) sales
  ON sales.source_system = refund.source_system
ORDER BY refund.source_system;

-- Every guardrail must be zero.
SELECT
    COUNT(*) FILTER (
        WHERE refund_value_status = 'recognized'
          AND COALESCE(recognized_refund_amount, 0) <= 0
    ) AS recognized_without_positive_value_rows,
    COUNT(*) FILTER (
        WHERE refund_value_status = 'monetary_value_unknown'
          AND recognized_refund_amount IS NOT NULL
    ) AS unknown_with_recognized_value_rows,
    COUNT(*) FILTER (
        WHERE source_system = 'lazada'
          AND refund_value_status = 'recognized'
    ) AS lazada_recognized_without_source_rows,
    COUNT(*) - COUNT(DISTINCT source_system || ':' || external_order_id)
        AS duplicate_source_order_rows
FROM public.vw_sales_refund_semantic;
