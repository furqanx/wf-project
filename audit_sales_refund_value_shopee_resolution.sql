-- Resolve Shopee settlement refund values against governed return events.
-- Read-only: no production facts are updated.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_shopee_settlement_refund ON COMMIT DROP AS
SELECT
    settlement.store_id,
    settlement.external_order_id,
    COUNT(*) AS settlement_rows,
    COUNT(DISTINCT settlement.sales_settlement_id) AS settlement_ids,
    COUNT(DISTINCT settlement.sales_order_id) AS linked_sales_orders,
    SUM(settlement.refund_amount) AS signed_refund_amount,
    -SUM(settlement.refund_amount) AS positive_refund_amount,
    MIN(COALESCE(settlement.settled_at, settlement.released_at))
        AS first_settlement_at,
    MAX(COALESCE(settlement.settled_at, settlement.released_at))
        AS last_settlement_at
FROM public.fact_sales_settlement settlement
WHERE settlement.is_active = TRUE
  AND settlement.source_system = 'shopee'
  AND settlement.refund_amount <> 0
GROUP BY settlement.store_id, settlement.external_order_id;

CREATE TEMP TABLE tmp_shopee_return_resolution ON COMMIT DROP AS
WITH return_header AS (
    SELECT
        returns.store_id,
        returns.external_order_id,
        COUNT(*) AS return_rows,
        COUNT(*) FILTER (
            WHERE returns.return_type = 'cancellation'
               OR LOWER(COALESCE(returns.return_status, '')) LIKE '%batal%'
        ) AS cancellation_rows,
        COUNT(*) FILTER (
            WHERE returns.return_type <> 'cancellation'
              AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE '%batal%'
              AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE
                  '%diproses%'
              AND (
                    returns.return_completed_at IS NOT NULL
                 OR LOWER(COALESCE(returns.return_status, '')) =
                    'permintaan disetujui'
              )
        ) AS completed_return_rows,
        STRING_AGG(
            DISTINCT COALESCE(returns.return_type, '') || ':'
                || COALESCE(returns.return_status, ''),
            ' | '
            ORDER BY COALESCE(returns.return_type, '') || ':'
                || COALESCE(returns.return_status, '')
        ) AS return_statuses,
        MIN(returns.return_requested_at) AS first_return_requested_at,
        MAX(returns.return_completed_at) AS last_return_completed_at
    FROM public.fact_sales_return returns
    WHERE returns.is_active = TRUE
      AND returns.source_system = 'shopee'
    GROUP BY returns.store_id, returns.external_order_id
),
return_item AS (
    SELECT
        returns.store_id,
        returns.external_order_id,
        SUM(COALESCE(items.return_qty, 0)) AS return_qty
    FROM public.fact_sales_return returns
    JOIN public.fact_sales_return_item items
      ON items.sales_return_id = returns.sales_return_id
     AND items.is_active = TRUE
    WHERE returns.is_active = TRUE
      AND returns.source_system = 'shopee'
    GROUP BY returns.store_id, returns.external_order_id
)
SELECT
    header.*,
    COALESCE(item.return_qty, 0) AS return_qty
FROM return_header header
LEFT JOIN return_item item
  ON item.store_id IS NOT DISTINCT FROM header.store_id
 AND item.external_order_id = header.external_order_id;

CREATE INDEX ON tmp_shopee_settlement_refund (store_id, external_order_id);
CREATE INDEX ON tmp_shopee_return_resolution (store_id, external_order_id);
ANALYZE tmp_shopee_settlement_refund;
ANALYZE tmp_shopee_return_resolution;

-- A. Settlement refund sign and linkage quality.
SELECT
    COUNT(*) AS refund_orders,
    SUM(settlement_rows) AS settlement_rows,
    COUNT(*) FILTER (WHERE signed_refund_amount >= 0)
        AS invalid_refund_sign_orders,
    COUNT(*) FILTER (WHERE linked_sales_orders = 0)
        AS orders_without_sales_order_link,
    COUNT(*) FILTER (WHERE linked_sales_orders > 1)
        AS orders_with_multiple_sales_order_links,
    SUM(signed_refund_amount) AS signed_refund_amount,
    SUM(positive_refund_amount) AS positive_refund_amount,
    MIN(first_settlement_at) AS min_settlement_at,
    MAX(last_settlement_at) AS max_settlement_at
FROM tmp_shopee_settlement_refund;

-- B. Return-state resolution for every monetary settlement refund.
SELECT
    CASE
        WHEN returns.external_order_id IS NULL
            THEN 'settlement_refund_without_return_event'
        WHEN returns.completed_return_rows > 0
            THEN 'completed_return_with_settlement_refund'
        WHEN returns.cancellation_rows > 0
            THEN 'cancellation_with_settlement_refund'
        ELSE 'nonfinal_return_with_settlement_refund'
    END AS resolution_status,
    COUNT(*) AS refund_orders,
    SUM(settlement.positive_refund_amount) AS positive_refund_amount,
    SUM(COALESCE(returns.return_qty, 0)) AS return_qty
FROM tmp_shopee_settlement_refund settlement
LEFT JOIN tmp_shopee_return_resolution returns
  ON returns.store_id IS NOT DISTINCT FROM settlement.store_id
 AND returns.external_order_id = settlement.external_order_id
GROUP BY resolution_status
ORDER BY resolution_status;

-- C. Coverage of completed returns by an authoritative monetary value.
SELECT
    COUNT(*) FILTER (WHERE completed_return_rows > 0)
        AS completed_return_orders,
    COUNT(*) FILTER (
        WHERE completed_return_rows > 0
          AND settlement.external_order_id IS NOT NULL
    ) AS completed_orders_with_settlement_value,
    COUNT(*) FILTER (
        WHERE completed_return_rows > 0
          AND settlement.external_order_id IS NULL
    ) AS completed_orders_without_settlement_value,
    SUM(settlement.positive_refund_amount) FILTER (
        WHERE completed_return_rows > 0
    ) AS recognized_refund_candidate_amount,
    SUM(returns.return_qty) FILTER (
        WHERE completed_return_rows > 0
          AND settlement.external_order_id IS NULL
    ) AS quantity_without_refund_value
FROM tmp_shopee_return_resolution returns
LEFT JOIN tmp_shopee_settlement_refund settlement
  ON settlement.store_id IS NOT DISTINCT FROM returns.store_id
 AND settlement.external_order_id = returns.external_order_id;

-- D. Monthly/store coverage for completed returns.
SELECT
    DATE_TRUNC('month', returns.last_return_completed_at)::date
        AS completion_month,
    returns.store_id,
    COUNT(*) AS completed_return_orders,
    COUNT(settlement.external_order_id) AS orders_with_settlement_value,
    COUNT(*) - COUNT(settlement.external_order_id)
        AS orders_without_settlement_value,
    SUM(settlement.positive_refund_amount) AS refund_amount
FROM tmp_shopee_return_resolution returns
LEFT JOIN tmp_shopee_settlement_refund settlement
  ON settlement.store_id IS NOT DISTINCT FROM returns.store_id
 AND settlement.external_order_id = returns.external_order_id
WHERE returns.completed_return_rows > 0
GROUP BY 1, 2
ORDER BY 1, 2;

-- E. Detail requiring review: monetary refunds without a completed return and
-- completed returns without a monetary settlement value.
SELECT
    COALESCE(settlement.store_id, returns.store_id) AS store_id,
    COALESCE(settlement.external_order_id, returns.external_order_id)
        AS external_order_id,
    CASE
        WHEN returns.external_order_id IS NULL
            THEN 'settlement_refund_without_return_event'
        WHEN returns.completed_return_rows = 0
            THEN 'settlement_refund_without_completed_return'
        WHEN settlement.external_order_id IS NULL
            THEN 'completed_return_without_settlement_value'
    END AS review_reason,
    returns.return_statuses,
    returns.return_qty,
    settlement.positive_refund_amount,
    returns.first_return_requested_at,
    returns.last_return_completed_at,
    settlement.first_settlement_at,
    settlement.last_settlement_at
FROM tmp_shopee_return_resolution returns
FULL JOIN tmp_shopee_settlement_refund settlement
  ON settlement.store_id IS NOT DISTINCT FROM returns.store_id
 AND settlement.external_order_id = returns.external_order_id
WHERE (
        settlement.external_order_id IS NOT NULL
        AND COALESCE(returns.completed_return_rows, 0) = 0
      )
   OR (
        returns.completed_return_rows > 0
        AND settlement.external_order_id IS NULL
      )
ORDER BY review_reason, store_id, external_order_id
LIMIT 250;

-- F. Duplicate identities should be impossible at the temporary order grain.
SELECT
    store_id,
    external_order_id,
    COUNT(*) AS rows
FROM tmp_shopee_settlement_refund
GROUP BY store_id, external_order_id
HAVING COUNT(*) > 1;

ROLLBACK;
