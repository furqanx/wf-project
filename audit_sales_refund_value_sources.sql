-- Audit monetary refund sources, coverage, and cross-fact overlap.
-- Read-only: no production facts are updated.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_refund_return ON COMMIT DROP AS
WITH return_header AS (
    SELECT
        returns.source_system,
        returns.store_id,
        returns.external_order_id,
        COUNT(*) AS return_rows,
        COUNT(*) FILTER (
            WHERE returns.return_type <> 'cancellation'
              AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE
                  '%dibatalkan%'
              AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE
                  '%diproses%'
              AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE
                  'in transit:%'
              AND (
                    returns.return_completed_at IS NOT NULL
                 OR LOWER(COALESCE(returns.return_status, '')) = 'selesai'
              )
        ) AS completed_return_rows,
        SUM(COALESCE(returns.refund_amount, 0)) AS header_refund_amount,
        SUM(COALESCE(returns.refund_amount, 0)) FILTER (
            WHERE returns.return_type <> 'cancellation'
              AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE
                  '%dibatalkan%'
              AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE
                  '%diproses%'
              AND LOWER(COALESCE(returns.return_status, '')) NOT LIKE
                  'in transit:%'
              AND (
                    returns.return_completed_at IS NOT NULL
                 OR LOWER(COALESCE(returns.return_status, '')) = 'selesai'
              )
        ) AS completed_header_refund_amount,
        MIN(returns.return_requested_at) AS first_return_at,
        MAX(returns.return_completed_at) AS last_completed_at
    FROM public.fact_sales_return returns
    WHERE returns.is_active = TRUE
    GROUP BY
        returns.source_system,
        returns.store_id,
        returns.external_order_id
),
return_item AS (
    SELECT
        returns.source_system,
        returns.store_id,
        returns.external_order_id,
        SUM(COALESCE(items.return_qty, 0)) AS return_qty,
        SUM(COALESCE(items.refund_item_amount, 0)) AS item_refund_amount
    FROM public.fact_sales_return returns
    JOIN public.fact_sales_return_item items
      ON items.sales_return_id = returns.sales_return_id
     AND items.is_active = TRUE
    WHERE returns.is_active = TRUE
    GROUP BY
        returns.source_system,
        returns.store_id,
        returns.external_order_id
)
SELECT
    header.*,
    COALESCE(item.return_qty, 0) AS return_qty,
    COALESCE(item.item_refund_amount, 0) AS item_refund_amount
FROM return_header header
LEFT JOIN return_item item
  ON item.source_system = header.source_system
 AND item.store_id IS NOT DISTINCT FROM header.store_id
 AND item.external_order_id = header.external_order_id;

CREATE TEMP TABLE tmp_refund_settlement ON COMMIT DROP AS
SELECT
    source_system,
    store_id,
    external_order_id,
    COUNT(*) AS settlement_rows,
    SUM(COALESCE(refund_amount, 0)) AS settlement_refund_amount
FROM public.fact_sales_settlement
WHERE is_active = TRUE
GROUP BY source_system, store_id, external_order_id;

CREATE TEMP TABLE tmp_refund_fee ON COMMIT DROP AS
SELECT
    detail.source_system,
    detail.store_id,
    detail.external_order_id,
    COUNT(*) AS fee_rows,
    SUM(detail.signed_fee_amount) AS signed_fee_refund_amount,
    SUM(detail.raw_fee_amount) AS raw_fee_refund_amount
FROM public.fact_sales_settlement_fee_detail detail
JOIN public.fee_type fee
  ON fee.fee_type_id = detail.fee_type_id
WHERE detail.is_active = TRUE
  AND fee.fee_code = 'order_refund_amount'
GROUP BY
    detail.source_system,
    detail.store_id,
    detail.external_order_id;

CREATE INDEX ON tmp_refund_return (
    source_system,
    store_id,
    external_order_id
);
CREATE INDEX ON tmp_refund_settlement (
    source_system,
    store_id,
    external_order_id
);
CREATE INDEX ON tmp_refund_fee (
    source_system,
    store_id,
    external_order_id
);
ANALYZE tmp_refund_return;
ANALYZE tmp_refund_settlement;
ANALYZE tmp_refund_fee;

-- A. Return event semantics and monetary availability.
WITH item_totals AS (
    SELECT
        sales_return_id,
        SUM(COALESCE(return_qty, 0)) AS return_qty,
        SUM(COALESCE(refund_item_amount, 0)) AS item_refund_amount
    FROM public.fact_sales_return_item
    WHERE is_active = TRUE
    GROUP BY sales_return_id
)
SELECT
    returns.source_system,
    returns.return_type,
    returns.return_status,
    COUNT(*) AS return_rows,
    COUNT(*) FILTER (
        WHERE returns.return_completed_at IS NOT NULL
           OR LOWER(COALESCE(returns.return_status, '')) = 'selesai'
    ) AS completion_marker_rows,
    COUNT(*) FILTER (
        WHERE COALESCE(returns.refund_amount, 0) <> 0
    ) AS header_monetary_rows,
    COUNT(*) FILTER (
        WHERE COALESCE(items.item_refund_amount, 0) <> 0
    ) AS item_monetary_rows,
    SUM(COALESCE(returns.refund_amount, 0)) AS header_refund_amount,
    SUM(COALESCE(items.item_refund_amount, 0)) AS item_refund_amount,
    SUM(COALESCE(items.return_qty, 0)) AS return_qty
FROM public.fact_sales_return returns
LEFT JOIN item_totals items
  ON items.sales_return_id = returns.sales_return_id
WHERE returns.is_active = TRUE
GROUP BY
    returns.source_system,
    returns.return_type,
    returns.return_status
ORDER BY returns.source_system, return_rows DESC;

-- B. Monetary source inventory by marketplace.
WITH source_inventory AS (
    SELECT
        source_system,
        'return_header'::text AS monetary_source,
        COUNT(*) FILTER (WHERE refund_amount <> 0) AS monetary_rows,
        SUM(COALESCE(refund_amount, 0)) AS refund_amount
    FROM public.fact_sales_return
    WHERE is_active = TRUE
    GROUP BY source_system

    UNION ALL

    SELECT
        source_system,
        'return_item'::text AS monetary_source,
        COUNT(*) FILTER (WHERE refund_item_amount <> 0) AS monetary_rows,
        SUM(COALESCE(refund_item_amount, 0)) AS refund_amount
    FROM public.fact_sales_return_item
    WHERE is_active = TRUE
    GROUP BY source_system

    UNION ALL

    SELECT
        source_system,
        'settlement_header'::text AS monetary_source,
        COUNT(*) FILTER (WHERE refund_amount <> 0) AS monetary_rows,
        SUM(COALESCE(refund_amount, 0)) AS refund_amount
    FROM public.fact_sales_settlement
    WHERE is_active = TRUE
    GROUP BY source_system

    UNION ALL

    SELECT
        detail.source_system,
        'settlement_fee_detail'::text AS monetary_source,
        COUNT(*) FILTER (WHERE detail.raw_fee_amount <> 0) AS monetary_rows,
        SUM(COALESCE(detail.raw_fee_amount, 0)) AS refund_amount
    FROM public.fact_sales_settlement_fee_detail detail
    JOIN public.fee_type fee
      ON fee.fee_type_id = detail.fee_type_id
    WHERE detail.is_active = TRUE
      AND fee.fee_code = 'order_refund_amount'
    GROUP BY detail.source_system
)
SELECT *
FROM source_inventory
ORDER BY source_system, monetary_source;

-- C. Cross-source coverage and amount agreement at source order grain.
WITH all_keys AS (
    SELECT source_system, store_id, external_order_id FROM tmp_refund_return
    UNION
    SELECT source_system, store_id, external_order_id
    FROM tmp_refund_settlement
    UNION
    SELECT source_system, store_id, external_order_id FROM tmp_refund_fee
),
comparison AS (
    SELECT
        keys.source_system,
        keys.store_id,
        keys.external_order_id,
        COALESCE(ret.completed_return_rows, 0) AS completed_return_rows,
        COALESCE(ret.completed_header_refund_amount, 0)
            AS return_refund_amount,
        COALESCE(ret.item_refund_amount, 0) AS item_refund_amount,
        COALESCE(settlement.settlement_refund_amount, 0)
            AS settlement_refund_amount,
        COALESCE(fee.raw_fee_refund_amount, 0) AS fee_refund_amount,
        ret.external_order_id IS NOT NULL AS has_return,
        settlement.external_order_id IS NOT NULL AS has_settlement,
        fee.external_order_id IS NOT NULL AS has_refund_fee
    FROM all_keys keys
    LEFT JOIN tmp_refund_return ret
      ON ret.source_system = keys.source_system
     AND ret.store_id IS NOT DISTINCT FROM keys.store_id
     AND ret.external_order_id = keys.external_order_id
    LEFT JOIN tmp_refund_settlement settlement
      ON settlement.source_system = keys.source_system
     AND settlement.store_id IS NOT DISTINCT FROM keys.store_id
     AND settlement.external_order_id = keys.external_order_id
    LEFT JOIN tmp_refund_fee fee
      ON fee.source_system = keys.source_system
     AND fee.store_id IS NOT DISTINCT FROM keys.store_id
     AND fee.external_order_id = keys.external_order_id
)
SELECT
    source_system,
    has_return,
    has_settlement,
    has_refund_fee,
    COUNT(*) AS order_keys,
    COUNT(*) FILTER (WHERE return_refund_amount <> 0)
        AS return_monetary_orders,
    COUNT(*) FILTER (WHERE settlement_refund_amount <> 0)
        AS settlement_monetary_orders,
    COUNT(*) FILTER (WHERE fee_refund_amount <> 0)
        AS fee_monetary_orders,
    COUNT(*) FILTER (
        WHERE return_refund_amount <> 0
          AND settlement_refund_amount <> 0
          AND ABS(return_refund_amount - settlement_refund_amount) <= 0.01
    ) AS return_settlement_exact_orders,
    COUNT(*) FILTER (
        WHERE return_refund_amount <> 0
          AND fee_refund_amount <> 0
          AND ABS(return_refund_amount - fee_refund_amount) <= 0.01
    ) AS return_fee_exact_orders,
    SUM(return_refund_amount) AS return_refund_amount,
    SUM(settlement_refund_amount) AS settlement_refund_amount,
    SUM(fee_refund_amount) AS fee_refund_amount
FROM comparison
GROUP BY source_system, has_return, has_settlement, has_refund_fee
ORDER BY source_system, has_return DESC, has_settlement DESC, has_refund_fee DESC;

-- D. Header versus item monetary agreement.
SELECT
    source_system,
    COUNT(*) FILTER (WHERE header_refund_amount <> 0)
        AS header_monetary_orders,
    COUNT(*) FILTER (WHERE item_refund_amount <> 0)
        AS item_monetary_orders,
    COUNT(*) FILTER (
        WHERE header_refund_amount <> 0
          AND item_refund_amount <> 0
          AND ABS(header_refund_amount - item_refund_amount) <= 0.01
    ) AS exact_header_item_orders,
    COUNT(*) FILTER (
        WHERE header_refund_amount <> 0
          AND item_refund_amount <> 0
          AND ABS(header_refund_amount - item_refund_amount) > 0.01
    ) AS mismatched_header_item_orders,
    SUM(header_refund_amount) AS header_refund_amount,
    SUM(item_refund_amount) AS item_refund_amount
FROM tmp_refund_return
GROUP BY source_system
ORDER BY source_system;

-- E. Completed return coverage without any monetary value.
SELECT
    source_system,
    COUNT(*) FILTER (WHERE completed_return_rows > 0)
        AS completed_return_orders,
    COUNT(*) FILTER (
        WHERE completed_return_rows > 0
          AND completed_header_refund_amount <> 0
    ) AS completed_orders_with_header_value,
    COUNT(*) FILTER (
        WHERE completed_return_rows > 0
          AND completed_header_refund_amount = 0
          AND item_refund_amount = 0
    ) AS completed_orders_without_return_value,
    SUM(return_qty) FILTER (
        WHERE completed_return_rows > 0
          AND completed_header_refund_amount = 0
          AND item_refund_amount = 0
    ) AS quantity_without_refund_value
FROM tmp_refund_return
GROUP BY source_system
ORDER BY source_system;

-- F. Existing semantic metric by source for comparison with approved sources.
SELECT
    source_system,
    SUM(completed_return_order_count) AS completed_return_orders,
    SUM(recognized_refund_amount) AS recognized_refund_amount,
    SUM(return_item_refund_amount) AS return_item_refund_amount,
    SUM(returned_units) AS returned_units
FROM public.vw_sales_semantic_order
GROUP BY source_system
ORDER BY source_system;

-- G. Duplicate return identities. Any result requires source review.
SELECT
    source_system,
    store_id,
    external_return_id,
    COUNT(*) AS return_rows,
    COUNT(DISTINCT external_order_id) AS external_orders,
    SUM(COALESCE(refund_amount, 0)) AS refund_amount
FROM public.fact_sales_return
WHERE is_active = TRUE
GROUP BY source_system, store_id, external_return_id
HAVING COUNT(*) > 1
ORDER BY return_rows DESC, source_system, external_return_id;

ROLLBACK;
