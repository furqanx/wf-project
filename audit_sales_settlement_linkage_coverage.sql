-- Read-only audit for Phase 2 settlement linkage and source coverage.
-- Temporary tables are session-scoped and do not modify public data.

\pset pager off
\set ON_ERROR_STOP on

SET statement_timeout = '15min';
SET lock_timeout = '10s';

BEGIN;

CREATE TEMP TABLE tmp_canonical_marketplace_order ON COMMIT DROP AS
SELECT
    sales_order_id,
    source_system,
    marketplace_id,
    store_id,
    external_order_id,
    order_date,
    order_status,
    net_order_amount,
    CASE
        WHEN LOWER(COALESCE(order_status, '')) IN (
            'batal', 'canceled', 'cancelled', 'dibatalkan'
        ) THEN FALSE
        ELSE TRUE
    END AS is_settlement_eligible
FROM public.vw_sales_order_analytics
WHERE source_system IN ('shopee', 'lazada', 'tiktok_tokopedia');

CREATE INDEX ON tmp_canonical_marketplace_order
    (source_system, external_order_id, store_id);
CREATE INDEX ON tmp_canonical_marketplace_order (sales_order_id);
ANALYZE tmp_canonical_marketplace_order;

CREATE TEMP TABLE tmp_unlinked_settlement_resolution ON COMMIT DROP AS
WITH candidates AS (
    SELECT
        settlements.sales_settlement_id,
        orders.sales_order_id,
        orders.store_id AS order_store_id,
        (orders.store_id = settlements.store_id) AS same_store
    FROM public.fact_sales_settlement settlements
    JOIN tmp_canonical_marketplace_order orders
        ON orders.source_system = settlements.source_system
       AND orders.external_order_id IN (
            settlements.external_order_id,
            settlements.external_order_item_id
       )
    WHERE settlements.is_active = TRUE
      AND settlements.sales_order_id IS NULL
), candidate_summary AS (
    SELECT
        sales_settlement_id,
        COUNT(DISTINCT sales_order_id) AS candidate_order_count,
        COUNT(DISTINCT sales_order_id) FILTER (WHERE same_store) AS same_store_candidate_count,
        MIN(sales_order_id) FILTER (WHERE same_store) AS same_store_sales_order_id,
        MIN(sales_order_id) AS any_store_sales_order_id
    FROM candidates
    GROUP BY sales_settlement_id
)
SELECT
    settlements.sales_settlement_id,
    settlements.source_system,
    settlements.marketplace_id,
    settlements.store_id AS settlement_store_id,
    stores.store_name AS settlement_store_name,
    settlements.external_order_id,
    settlements.external_order_item_id,
    settlements.settlement_type,
    settlements.order_created_at,
    settlements.settled_at,
    settlements.released_at,
    settlements.settlement_amount,
    settlements.source_file,
    COALESCE(summary.candidate_order_count, 0) AS candidate_order_count,
    COALESCE(summary.same_store_candidate_count, 0) AS same_store_candidate_count,
    CASE
        WHEN summary.same_store_candidate_count = 1
            THEN summary.same_store_sales_order_id
        WHEN summary.candidate_order_count = 1
            THEN summary.any_store_sales_order_id
        ELSE NULL
    END AS proposed_sales_order_id,
    CASE
        WHEN summary.same_store_candidate_count = 1
            THEN 'recoverable_exact_source_order_store'
        WHEN summary.candidate_order_count = 1
            THEN 'recoverable_unique_source_order_cross_store'
        WHEN summary.candidate_order_count > 1
            THEN 'ambiguous_multiple_canonical_orders'
        WHEN COALESCE(settlements.settlement_type, '') <> 'order_settlement'
            THEN 'non_order_settlement'
        ELSE 'missing_historical_phase1_order'
    END AS linkage_classification
FROM public.fact_sales_settlement settlements
LEFT JOIN candidate_summary summary
    ON summary.sales_settlement_id = settlements.sales_settlement_id
LEFT JOIN public.dim_store stores
    ON stores.store_id = settlements.store_id
WHERE settlements.is_active = TRUE
  AND settlements.sales_order_id IS NULL;

CREATE INDEX ON tmp_unlinked_settlement_resolution (source_system, linkage_classification);
ANALYZE tmp_unlinked_settlement_resolution;

-- A. Classification of every currently unlinked settlement row.
SELECT
    source_system,
    linkage_classification,
    COUNT(*) AS settlement_rows,
    COUNT(DISTINCT external_order_id) AS external_order_ids,
    SUM(COALESCE(settlement_amount, 0)) AS settlement_amount
FROM tmp_unlinked_settlement_resolution
GROUP BY source_system, linkage_classification
ORDER BY source_system, linkage_classification;

-- B. Proposed safe repairs. Only these two classes are eligible for update.
SELECT
    source_system,
    linkage_classification,
    COUNT(*) AS repairable_rows,
    COUNT(DISTINCT proposed_sales_order_id) AS target_orders,
    SUM(COALESCE(settlement_amount, 0)) AS repairable_settlement_amount
FROM tmp_unlinked_settlement_resolution
WHERE proposed_sales_order_id IS NOT NULL
GROUP BY source_system, linkage_classification
ORDER BY source_system, linkage_classification;

-- C. Store mismatch detail for unique cross-store candidates.
SELECT
    resolution.source_system,
    resolution.sales_settlement_id,
    resolution.external_order_id,
    resolution.settlement_store_id,
    resolution.settlement_store_name,
    orders.store_id AS proposed_order_store_id,
    order_stores.store_name AS proposed_order_store_name,
    resolution.proposed_sales_order_id,
    resolution.settlement_amount,
    resolution.source_file
FROM tmp_unlinked_settlement_resolution resolution
JOIN tmp_canonical_marketplace_order orders
    ON orders.sales_order_id = resolution.proposed_sales_order_id
LEFT JOIN public.dim_store order_stores
    ON order_stores.store_id = orders.store_id
WHERE resolution.linkage_classification = 'recoverable_unique_source_order_cross_store'
ORDER BY resolution.source_system, resolution.sales_settlement_id
LIMIT 200;

-- D. Persist detailed audit exports outside PostgreSQL for review.
\copy (SELECT * FROM tmp_unlinked_settlement_resolution ORDER BY source_system, linkage_classification, sales_settlement_id) TO '/tmp/sales_settlement_unlinked_classification.csv' WITH (FORMAT CSV, HEADER TRUE)

-- E. Coverage bounds are based on the order cohort represented by settlement
-- source rows, not settlement release month.
CREATE TEMP TABLE tmp_settlement_source_bounds ON COMMIT DROP AS
SELECT
    source_system,
    store_id,
    MIN(order_created_at::date) AS min_source_order_date,
    MAX(order_created_at::date) AS max_source_order_date
FROM public.fact_sales_settlement
WHERE is_active = TRUE
  AND order_created_at IS NOT NULL
GROUP BY source_system, store_id;

CREATE TEMP TABLE tmp_order_settlement_coverage ON COMMIT DROP AS
WITH linked AS (
    SELECT DISTINCT sales_order_id
    FROM public.fact_sales_settlement
    WHERE is_active = TRUE
      AND sales_order_id IS NOT NULL
), recoverable AS (
    SELECT DISTINCT proposed_sales_order_id AS sales_order_id
    FROM tmp_unlinked_settlement_resolution
    WHERE proposed_sales_order_id IS NOT NULL
), order_status AS (
    SELECT
        orders.*,
        (linked.sales_order_id IS NOT NULL) AS has_linked_settlement,
        (recoverable.sales_order_id IS NOT NULL) AS has_recoverable_settlement,
        bounds.min_source_order_date,
        bounds.max_source_order_date
    FROM tmp_canonical_marketplace_order orders
    LEFT JOIN linked
        ON linked.sales_order_id = orders.sales_order_id
    LEFT JOIN recoverable
        ON recoverable.sales_order_id = orders.sales_order_id
    LEFT JOIN tmp_settlement_source_bounds bounds
        ON bounds.source_system = orders.source_system
       AND bounds.store_id IS NOT DISTINCT FROM orders.store_id
    WHERE orders.is_settlement_eligible = TRUE
)
SELECT
    source_system,
    marketplace_id,
    store_id,
    DATE_TRUNC('month', order_date)::date AS order_month,
    COUNT(*) AS eligible_order_rows,
    COUNT(*) FILTER (WHERE has_linked_settlement) AS available_linked_rows,
    COUNT(*) FILTER (
        WHERE NOT has_linked_settlement AND has_recoverable_settlement
    ) AS available_unlinked_recoverable_rows,
    COUNT(*) FILTER (
        WHERE NOT has_linked_settlement
          AND NOT has_recoverable_settlement
          AND order_date BETWEEN min_source_order_date AND max_source_order_date
    ) AS source_period_available_but_settlement_missing_rows,
    COUNT(*) FILTER (
        WHERE NOT has_linked_settlement
          AND NOT has_recoverable_settlement
          AND (
              min_source_order_date IS NULL
              OR order_date < min_source_order_date
              OR order_date > max_source_order_date
          )
    ) AS historically_unavailable_rows,
    SUM(net_order_amount) AS eligible_revenue,
    SUM(net_order_amount) FILTER (WHERE has_linked_settlement) AS linked_revenue,
    MIN(min_source_order_date) AS min_source_order_date,
    MAX(max_source_order_date) AS max_source_order_date
FROM order_status
GROUP BY source_system, marketplace_id, store_id, DATE_TRUNC('month', order_date)::date;

-- F. Coverage by source after accounting for safe linkage candidates.
SELECT
    source_system,
    SUM(eligible_order_rows) AS eligible_order_rows,
    SUM(available_linked_rows) AS currently_linked_rows,
    SUM(available_unlinked_recoverable_rows) AS recoverable_link_rows,
    SUM(source_period_available_but_settlement_missing_rows) AS source_available_missing_rows,
    SUM(historically_unavailable_rows) AS historically_unavailable_rows,
    ROUND(
        100.0 * (
            SUM(available_linked_rows) + SUM(available_unlinked_recoverable_rows)
        ) / NULLIF(SUM(eligible_order_rows), 0),
        2
    ) AS projected_linkage_coverage_pct
FROM tmp_order_settlement_coverage
GROUP BY source_system
ORDER BY source_system;

-- G. Coverage by month and store for profitability availability flags.
SELECT
    coverage.source_system,
    coverage.order_month,
    coverage.store_id,
    stores.store_name,
    coverage.eligible_order_rows,
    coverage.available_linked_rows,
    coverage.available_unlinked_recoverable_rows,
    coverage.source_period_available_but_settlement_missing_rows,
    coverage.historically_unavailable_rows,
    ROUND(
        100.0 * (
            coverage.available_linked_rows
            + coverage.available_unlinked_recoverable_rows
        ) / NULLIF(coverage.eligible_order_rows, 0),
        2
    ) AS projected_linkage_coverage_pct,
    coverage.min_source_order_date,
    coverage.max_source_order_date
FROM tmp_order_settlement_coverage coverage
LEFT JOIN public.dim_store stores
    ON stores.store_id = coverage.store_id
ORDER BY coverage.source_system, coverage.order_month, coverage.store_id;

\copy (SELECT coverage.*, stores.store_name FROM tmp_order_settlement_coverage coverage LEFT JOIN public.dim_store stores ON stores.store_id = coverage.store_id ORDER BY coverage.source_system, coverage.order_month, coverage.store_id) TO '/tmp/sales_settlement_monthly_store_coverage.csv' WITH (FORMAT CSV, HEADER TRUE)

ROLLBACK;
