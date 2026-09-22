-- Diagnose Shopee adjustments whose related order exists under another store.
-- Read-only: no production facts are updated.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_shopee_cross_store ON COMMIT DROP AS
WITH adjustment AS (
    SELECT
        fssa.*,
        NULLIF(BTRIM(fssa.related_external_order_id), '')
            AS clean_related_external_order_id
    FROM public.fact_sales_settlement_adjustment fssa
    WHERE fssa.is_active = TRUE
      AND fssa.source_system = 'shopee'
      AND NULLIF(BTRIM(fssa.related_external_order_id), '') IS NOT NULL
),
candidate AS (
    SELECT
        adjustment.sales_settlement_adjustment_id,
        orders.sales_order_id AS candidate_sales_order_id
    FROM adjustment
    JOIN public.fact_sales_order orders
      ON orders.source_system = adjustment.source_system
     AND orders.sales_channel_type = 'online'
     AND orders.is_active = TRUE
     AND orders.external_order_id =
         adjustment.clean_related_external_order_id
    WHERE orders.store_id IS DISTINCT FROM adjustment.store_id
)
SELECT
    adjustment.sales_settlement_adjustment_id,
    adjustment.store_id AS adjustment_store_id,
    adjustment_store.store_code AS adjustment_store_code,
    adjustment_store.store_name AS adjustment_store_name,
    adjustment.sales_order_id AS direct_sales_order_id,
    adjustment.sales_settlement_id,
    adjustment.clean_related_external_order_id AS related_external_order_id,
    adjustment.raw_adjustment_name,
    adjustment.signed_adjustment_amount,
    adjustment.adjustment_occurred_at,
    adjustment.source_file AS adjustment_source_file,
    adjustment.source_row_number AS adjustment_source_row_number,
    settlement.external_order_id AS settlement_external_order_id,
    settlement.store_id AS settlement_store_id,
    settlement_store.store_code AS settlement_store_code,
    settlement.sales_order_id AS settlement_sales_order_id,
    settlement.settled_at,
    settlement.released_at,
    settlement.source_file AS settlement_source_file,
    orders.sales_order_id AS candidate_sales_order_id,
    orders.external_order_id AS order_external_order_id,
    orders.store_id AS order_store_id,
    order_store.store_code AS order_store_code,
    order_store.store_name AS order_store_name,
    orders.order_date,
    orders.order_status,
    orders.net_order_amount,
    orders.source_file AS order_source_file,
    CASE
        WHEN adjustment.sales_settlement_id IS NOT NULL
         AND settlement.sales_order_id = orders.sales_order_id
            THEN 'existing_settlement_order_link'
        WHEN adjustment.sales_settlement_id IS NULL
            THEN 'unlinked_cross_store_candidate'
        ELSE 'other_cross_store_case'
    END AS linkage_case,
    CASE
        WHEN adjustment.clean_related_external_order_id =
             settlement.external_order_id
         AND adjustment.clean_related_external_order_id =
             orders.external_order_id
            THEN TRUE
        ELSE FALSE
    END AS external_order_id_consistent,
    CASE
        WHEN adjustment.store_id = settlement.store_id
            THEN TRUE
        ELSE FALSE
    END AS adjustment_settlement_store_consistent
FROM adjustment
JOIN candidate
  ON candidate.sales_settlement_adjustment_id =
     adjustment.sales_settlement_adjustment_id
JOIN public.fact_sales_order orders
  ON orders.sales_order_id = candidate.candidate_sales_order_id
LEFT JOIN public.fact_sales_settlement settlement
  ON settlement.sales_settlement_id = adjustment.sales_settlement_id
LEFT JOIN public.dim_store adjustment_store
  ON adjustment_store.store_id = adjustment.store_id
LEFT JOIN public.dim_store settlement_store
  ON settlement_store.store_id = settlement.store_id
LEFT JOIN public.dim_store order_store
  ON order_store.store_id = orders.store_id;

ANALYZE tmp_shopee_cross_store;

-- A. Full six-case evidence.
SELECT *
FROM tmp_shopee_cross_store
ORDER BY
    linkage_case,
    sales_settlement_adjustment_id,
    candidate_sales_order_id;

-- B. Store-pair pattern. A repeated pair usually indicates a historical store
-- mapping issue rather than random order-ID collision.
SELECT
    adjustment_store_id,
    adjustment_store_code,
    settlement_store_id,
    settlement_store_code,
    order_store_id,
    order_store_code,
    linkage_case,
    COUNT(*) AS adjustment_rows,
    COUNT(DISTINCT related_external_order_id) AS external_orders,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount,
    MIN(adjustment_occurred_at) AS min_adjustment_at,
    MAX(adjustment_occurred_at) AS max_adjustment_at
FROM tmp_shopee_cross_store
GROUP BY
    adjustment_store_id,
    adjustment_store_code,
    settlement_store_id,
    settlement_store_code,
    order_store_id,
    order_store_code,
    linkage_case
ORDER BY adjustment_rows DESC, adjustment_store_code, order_store_code;

-- C. Candidate uniqueness and consistency. No case may have more than one
-- order candidate before any remediation is considered.
SELECT
    sales_settlement_adjustment_id,
    COUNT(DISTINCT candidate_sales_order_id) AS candidate_orders,
    BOOL_AND(external_order_id_consistent) AS external_order_id_consistent,
    BOOL_AND(adjustment_settlement_store_consistent) FILTER (
        WHERE sales_settlement_id IS NOT NULL
    ) AS adjustment_settlement_store_consistent,
    COUNT(*) FILTER (
        WHERE linkage_case = 'existing_settlement_order_link'
    ) AS existing_settlement_order_link_rows,
    COUNT(*) FILTER (
        WHERE linkage_case = 'unlinked_cross_store_candidate'
    ) AS unlinked_cross_store_candidate_rows
FROM tmp_shopee_cross_store
GROUP BY sales_settlement_adjustment_id
ORDER BY sales_settlement_adjustment_id;

ROLLBACK;
