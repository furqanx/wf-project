-- Resolve authoritative refund values for Shopee and TikTok/Tokopedia.
-- Read-only: no production facts are updated.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_refund_resolution ON COMMIT DROP AS
WITH return_event AS (
    SELECT
        source_system,
        store_id,
        external_order_id,
        COUNT(*) AS return_rows,
        COUNT(*) FILTER (
            WHERE return_type <> 'cancellation'
              AND LOWER(COALESCE(return_status, '')) NOT LIKE '%dibatalkan%'
              AND LOWER(COALESCE(return_status, '')) NOT LIKE '%diproses%'
              AND LOWER(COALESCE(return_status, '')) NOT LIKE 'in transit:%'
              AND (
                    return_completed_at IS NOT NULL
                 OR LOWER(COALESCE(return_status, '')) = 'selesai'
              )
        ) AS completed_non_cancellation_rows,
        STRING_AGG(
            DISTINCT COALESCE(return_type, '') || ':'
                || COALESCE(return_status, ''),
            ' | '
            ORDER BY COALESCE(return_type, '') || ':'
                || COALESCE(return_status, '')
        ) AS return_status_signature,
        SUM(COALESCE(refund_amount, 0)) FILTER (
            WHERE return_type <> 'cancellation'
              AND LOWER(COALESCE(return_status, '')) NOT LIKE '%dibatalkan%'
              AND LOWER(COALESCE(return_status, '')) NOT LIKE '%diproses%'
              AND LOWER(COALESCE(return_status, '')) NOT LIKE 'in transit:%'
              AND (
                    return_completed_at IS NOT NULL
                 OR LOWER(COALESCE(return_status, '')) = 'selesai'
              )
        ) AS completed_return_refund_amount
    FROM public.fact_sales_return
    WHERE is_active = TRUE
      AND source_system IN ('shopee', 'tiktok_tokopedia')
    GROUP BY source_system, store_id, external_order_id
),
settlement AS (
    SELECT
        source_system,
        store_id,
        external_order_id,
        COUNT(*) AS settlement_rows,
        SUM(COALESCE(refund_amount, 0)) AS signed_settlement_refund_amount,
        SUM(ABS(COALESCE(refund_amount, 0))) AS absolute_settlement_refund_amount
    FROM public.fact_sales_settlement
    WHERE is_active = TRUE
      AND source_system IN ('shopee', 'tiktok_tokopedia')
    GROUP BY source_system, store_id, external_order_id
),
all_keys AS (
    SELECT source_system, store_id, external_order_id FROM return_event
    UNION
    SELECT source_system, store_id, external_order_id FROM settlement
)
SELECT
    keys.source_system,
    keys.store_id,
    keys.external_order_id,
    orders.sales_order_id,
    orders.order_status,
    COALESCE(event.return_rows, 0) AS return_rows,
    COALESCE(event.completed_non_cancellation_rows, 0)
        AS completed_non_cancellation_rows,
    event.return_status_signature,
    COALESCE(event.completed_return_refund_amount, 0)
        AS completed_return_refund_amount,
    COALESCE(settlement.settlement_rows, 0) AS settlement_rows,
    COALESCE(settlement.signed_settlement_refund_amount, 0)
        AS signed_settlement_refund_amount,
    COALESCE(settlement.absolute_settlement_refund_amount, 0)
        AS absolute_settlement_refund_amount,
    event.external_order_id IS NOT NULL AS has_return_event,
    settlement.external_order_id IS NOT NULL AS has_settlement
FROM all_keys keys
LEFT JOIN return_event event
  ON event.source_system = keys.source_system
 AND event.store_id IS NOT DISTINCT FROM keys.store_id
 AND event.external_order_id = keys.external_order_id
LEFT JOIN settlement
  ON settlement.source_system = keys.source_system
 AND settlement.store_id IS NOT DISTINCT FROM keys.store_id
 AND settlement.external_order_id = keys.external_order_id
LEFT JOIN public.vw_sales_order_analytics orders
  ON orders.source_system = keys.source_system
 AND orders.store_id IS NOT DISTINCT FROM keys.store_id
 AND orders.external_order_id = keys.external_order_id;

CREATE INDEX ON tmp_refund_resolution (
    source_system,
    store_id,
    external_order_id
);
ANALYZE tmp_refund_resolution;

-- A. Settlement monetary coverage by return semantics.
SELECT
    source_system,
    has_return_event,
    has_settlement,
    completed_non_cancellation_rows > 0 AS is_completed_return,
    return_status_signature,
    COUNT(*) AS order_rows,
    COUNT(*) FILTER (
        WHERE absolute_settlement_refund_amount > 0
    ) AS orders_with_settlement_refund,
    COUNT(*) FILTER (
        WHERE completed_return_refund_amount > 0
    ) AS orders_with_return_refund,
    SUM(completed_return_refund_amount) AS completed_return_refund_amount,
    SUM(signed_settlement_refund_amount) AS signed_settlement_refund_amount,
    SUM(absolute_settlement_refund_amount)
        AS absolute_settlement_refund_amount
FROM tmp_refund_resolution
WHERE has_return_event
   OR absolute_settlement_refund_amount > 0
GROUP BY
    source_system,
    has_return_event,
    has_settlement,
    completed_non_cancellation_rows > 0,
    return_status_signature
ORDER BY source_system, order_rows DESC, return_status_signature;

-- B. Amount agreement after settlement sign normalization.
SELECT
    source_system,
    COUNT(*) FILTER (
        WHERE completed_return_refund_amount > 0
    ) AS return_monetary_orders,
    COUNT(*) FILTER (
        WHERE absolute_settlement_refund_amount > 0
    ) AS settlement_monetary_orders,
    COUNT(*) FILTER (
        WHERE completed_return_refund_amount > 0
          AND absolute_settlement_refund_amount > 0
    ) AS overlapping_monetary_orders,
    COUNT(*) FILTER (
        WHERE completed_return_refund_amount > 0
          AND absolute_settlement_refund_amount > 0
          AND ABS(
              completed_return_refund_amount
              - absolute_settlement_refund_amount
          ) <= 0.01
    ) AS exact_amount_orders,
    COUNT(*) FILTER (
        WHERE completed_return_refund_amount > 0
          AND absolute_settlement_refund_amount > 0
          AND ABS(
              completed_return_refund_amount
              - absolute_settlement_refund_amount
          ) > 0.01
    ) AS mismatched_amount_orders,
    SUM(completed_return_refund_amount) AS completed_return_refund_amount,
    SUM(absolute_settlement_refund_amount)
        AS absolute_settlement_refund_amount
FROM tmp_refund_resolution
GROUP BY source_system
ORDER BY source_system;

-- C. Proposed authoritative recognized refund. TikTok uses completed return
-- header value. Shopee uses settlement value only when supported by a
-- completed, non-cancellation return event.
SELECT
    source_system,
    COUNT(*) FILTER (
        WHERE completed_non_cancellation_rows > 0
    ) AS completed_return_orders,
    COUNT(*) FILTER (
        WHERE completed_non_cancellation_rows > 0
          AND CASE
                  WHEN source_system = 'tiktok_tokopedia'
                      THEN completed_return_refund_amount
                  WHEN source_system = 'shopee'
                      THEN absolute_settlement_refund_amount
                  ELSE 0
              END > 0
    ) AS recognized_refund_orders,
    COUNT(*) FILTER (
        WHERE completed_non_cancellation_rows > 0
          AND CASE
                  WHEN source_system = 'tiktok_tokopedia'
                      THEN completed_return_refund_amount
                  WHEN source_system = 'shopee'
                      THEN absolute_settlement_refund_amount
                  ELSE 0
              END = 0
    ) AS completed_orders_without_refund_value,
    SUM(
        CASE
            WHEN completed_non_cancellation_rows = 0 THEN 0
            WHEN source_system = 'tiktok_tokopedia'
                THEN completed_return_refund_amount
            WHEN source_system = 'shopee'
                THEN absolute_settlement_refund_amount
            ELSE 0
        END
    ) AS proposed_recognized_refund_amount
FROM tmp_refund_resolution
WHERE source_system IN ('shopee', 'tiktok_tokopedia')
GROUP BY source_system
ORDER BY source_system;

-- D. Settlement refund without supporting return event remains excluded.
SELECT
    source_system,
    order_status,
    COUNT(*) AS unsupported_settlement_refund_orders,
    SUM(absolute_settlement_refund_amount)
        AS unsupported_settlement_refund_amount
FROM tmp_refund_resolution
WHERE absolute_settlement_refund_amount > 0
  AND completed_non_cancellation_rows = 0
GROUP BY source_system, order_status
ORDER BY source_system, unsupported_settlement_refund_orders DESC;

-- E. Largest amount mismatches for source investigation.
SELECT
    source_system,
    store_id,
    external_order_id,
    sales_order_id,
    order_status,
    return_status_signature,
    completed_return_refund_amount,
    absolute_settlement_refund_amount,
    absolute_settlement_refund_amount - completed_return_refund_amount
        AS amount_delta
FROM tmp_refund_resolution
WHERE completed_return_refund_amount > 0
  AND absolute_settlement_refund_amount > 0
  AND ABS(
      completed_return_refund_amount - absolute_settlement_refund_amount
  ) > 0.01
ORDER BY ABS(
    completed_return_refund_amount - absolute_settlement_refund_amount
) DESC
LIMIT 100;

-- F. Duplicate analytical keys must be zero.
SELECT
    COUNT(*) - COUNT(DISTINCT CONCAT_WS(
        ':',
        source_system,
        COALESCE(store_id::text, ''),
        external_order_id
    )) AS duplicate_resolution_keys,
    COUNT(*) FILTER (
        WHERE source_system = 'shopee'
          AND completed_non_cancellation_rows > 0
          AND signed_settlement_refund_amount > 0
    ) AS invalid_shopee_settlement_sign_rows,
    COUNT(*) FILTER (
        WHERE source_system = 'tiktok_tokopedia'
          AND completed_return_refund_amount < 0
    ) AS invalid_tiktok_return_sign_rows
FROM tmp_refund_resolution;

ROLLBACK;
