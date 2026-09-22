-- Read-only canonical valid-order marketplace fee coverage.
-- Temporary tables avoid recalculating the heavy semantic views repeatedly.

\pset pager off
\set ON_ERROR_STOP on

SET statement_timeout = '30min';
SET lock_timeout = '10s';

BEGIN;

CREATE TEMP TABLE tmp_fee_order_classification ON COMMIT DROP AS
SELECT
    sales_order_id,
    source_system,
    store_id,
    external_order_id,
    net_order_amount,
    product_quantity_signature,
    order_status,
    is_analytics_included,
    CASE
        WHEN LOWER(COALESCE(order_status, '')) IN (
            'batal', 'canceled', 'cancelled', 'dibatalkan'
        ) THEN FALSE
        ELSE TRUE
    END AS is_valid_order
FROM public.vw_sales_order_channel_classification
WHERE source_system IN ('shopee', 'lazada', 'tiktok_tokopedia');

CREATE INDEX ON tmp_fee_order_classification (sales_order_id);
CREATE INDEX ON tmp_fee_order_classification (
    source_system,
    external_order_id,
    net_order_amount,
    product_quantity_signature
);
ANALYZE tmp_fee_order_classification;

CREATE TEMP TABLE tmp_fee_order_resolution ON COMMIT DROP AS
SELECT
    candidate.sales_order_id AS source_sales_order_id,
    canonical.sales_order_id AS canonical_sales_order_id
FROM tmp_fee_order_classification candidate
JOIN tmp_fee_order_classification canonical
    ON canonical.source_system = candidate.source_system
   AND canonical.external_order_id = candidate.external_order_id
   AND COALESCE(canonical.net_order_amount, 0) = COALESCE(candidate.net_order_amount, 0)
   AND canonical.product_quantity_signature = candidate.product_quantity_signature
   AND canonical.is_analytics_included = TRUE;

CREATE UNIQUE INDEX ON tmp_fee_order_resolution (source_sales_order_id);
CREATE INDEX ON tmp_fee_order_resolution (canonical_sales_order_id);
ANALYZE tmp_fee_order_resolution;

CREATE TEMP TABLE tmp_fee_by_canonical_order ON COMMIT DROP AS
SELECT
    resolution.canonical_sales_order_id AS sales_order_id,
    COUNT(*) AS fee_rows,
    SUM(fees.signed_fee_amount) AS signed_fee_amount
FROM public.fact_sales_settlement_fee_detail fees
JOIN tmp_fee_order_resolution resolution
    ON resolution.source_sales_order_id = fees.sales_order_id
WHERE fees.is_active = TRUE
  AND fees.sales_order_id IS NOT NULL
GROUP BY resolution.canonical_sales_order_id;

CREATE UNIQUE INDEX ON tmp_fee_by_canonical_order (sales_order_id);
ANALYZE tmp_fee_by_canonical_order;

SELECT
    orders.source_system,
    COUNT(*) AS eligible_orders,
    COUNT(fees.sales_order_id) AS orders_with_fee,
    COUNT(*) - COUNT(fees.sales_order_id) AS orders_with_unknown_fee,
    ROUND(
        100.0 * COUNT(fees.sales_order_id) / NULLIF(COUNT(*), 0),
        2
    ) AS fee_coverage_pct,
    SUM(COALESCE(fees.fee_rows, 0)) AS fee_rows,
    SUM(fees.signed_fee_amount) AS signed_fee_amount
FROM tmp_fee_order_classification orders
LEFT JOIN tmp_fee_by_canonical_order fees
    ON fees.sales_order_id = orders.sales_order_id
WHERE orders.is_analytics_included = TRUE
  AND orders.is_valid_order = TRUE
GROUP BY orders.source_system
ORDER BY orders.source_system;

ROLLBACK;
