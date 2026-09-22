-- Diagnose unresolved TikTok/Tokopedia adjustment linkage using both source
-- identities: related_order_id and order_adjustment_id.
-- Read-only: no production facts are updated.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_tiktok_adjustment_target ON COMMIT DROP AS
SELECT
    adjustment.sales_settlement_adjustment_id,
    adjustment.store_id,
    store.store_code,
    adjustment.external_adjustment_id,
    NULLIF(BTRIM(adjustment.related_external_order_id), '')
        AS related_external_order_id,
    adjustment.raw_transaction_type,
    adjustment.raw_adjustment_name,
    adjustment.signed_adjustment_amount,
    adjustment.adjustment_occurred_at,
    adjustment.source_file,
    adjustment.source_row_number
FROM public.fact_sales_settlement_adjustment adjustment
LEFT JOIN public.dim_store store
  ON store.store_id = adjustment.store_id
WHERE adjustment.is_active = TRUE
  AND adjustment.source_system = 'tiktok_tokopedia'
  AND adjustment.sales_order_id IS NULL
  AND adjustment.sales_settlement_id IS NULL;

CREATE INDEX ON tmp_tiktok_adjustment_target (external_adjustment_id);
CREATE INDEX ON tmp_tiktok_adjustment_target (related_external_order_id);
ANALYZE tmp_tiktok_adjustment_target;

CREATE TEMP TABLE tmp_tiktok_candidate_summary ON COMMIT DROP AS
WITH related_order_match AS (
    SELECT
        target.sales_settlement_adjustment_id,
        COUNT(DISTINCT orders.sales_order_id) AS candidate_count,
        COUNT(DISTINCT orders.sales_order_id) FILTER (
            WHERE orders.store_id = target.store_id
        ) AS same_store_candidate_count,
        MIN(orders.sales_order_id) FILTER (
            WHERE orders.store_id = target.store_id
        ) AS same_store_sales_order_id
    FROM tmp_tiktok_adjustment_target target
    LEFT JOIN public.fact_sales_order orders
      ON orders.source_system = 'tiktok_tokopedia'
     AND orders.sales_channel_type = 'online'
     AND orders.is_active = TRUE
     AND orders.external_order_id = target.related_external_order_id
    GROUP BY target.sales_settlement_adjustment_id
),
related_settlement_match AS (
    SELECT
        target.sales_settlement_adjustment_id,
        COUNT(DISTINCT settlement.sales_settlement_id) AS candidate_count,
        COUNT(DISTINCT settlement.sales_settlement_id) FILTER (
            WHERE settlement.store_id = target.store_id
        ) AS same_store_candidate_count,
        MIN(settlement.sales_settlement_id) FILTER (
            WHERE settlement.store_id = target.store_id
        ) AS same_store_sales_settlement_id,
        MIN(settlement.sales_order_id) FILTER (
            WHERE settlement.store_id = target.store_id
        ) AS same_store_settlement_order_id
    FROM tmp_tiktok_adjustment_target target
    LEFT JOIN public.fact_sales_settlement settlement
      ON settlement.source_system = 'tiktok_tokopedia'
     AND settlement.sales_channel_type = 'online'
     AND settlement.is_active = TRUE
     AND settlement.external_order_id = target.related_external_order_id
    GROUP BY target.sales_settlement_adjustment_id
),
adjustment_settlement_match AS (
    SELECT
        target.sales_settlement_adjustment_id,
        COUNT(DISTINCT settlement.sales_settlement_id) AS candidate_count,
        COUNT(DISTINCT settlement.sales_settlement_id) FILTER (
            WHERE settlement.store_id = target.store_id
        ) AS same_store_candidate_count,
        MIN(settlement.sales_settlement_id) FILTER (
            WHERE settlement.store_id = target.store_id
        ) AS same_store_sales_settlement_id,
        MIN(settlement.sales_order_id) FILTER (
            WHERE settlement.store_id = target.store_id
        ) AS same_store_settlement_order_id
    FROM tmp_tiktok_adjustment_target target
    LEFT JOIN public.fact_sales_settlement settlement
      ON settlement.source_system = 'tiktok_tokopedia'
     AND settlement.sales_channel_type = 'online'
     AND settlement.is_active = TRUE
     AND settlement.external_order_id = target.external_adjustment_id
    GROUP BY target.sales_settlement_adjustment_id
),
adjustment_order_match AS (
    SELECT
        target.sales_settlement_adjustment_id,
        COUNT(DISTINCT orders.sales_order_id) AS candidate_count,
        COUNT(DISTINCT orders.sales_order_id) FILTER (
            WHERE orders.store_id = target.store_id
        ) AS same_store_candidate_count,
        MIN(orders.sales_order_id) FILTER (
            WHERE orders.store_id = target.store_id
        ) AS same_store_sales_order_id
    FROM tmp_tiktok_adjustment_target target
    LEFT JOIN public.fact_sales_order orders
      ON orders.source_system = 'tiktok_tokopedia'
     AND orders.sales_channel_type = 'online'
     AND orders.is_active = TRUE
     AND orders.external_order_id = target.external_adjustment_id
    GROUP BY target.sales_settlement_adjustment_id
)
SELECT
    target.*,
    related_order.candidate_count AS related_order_candidates,
    related_order.same_store_candidate_count
        AS related_order_same_store_candidates,
    related_order.same_store_sales_order_id
        AS related_order_same_store_sales_order_id,
    related_settlement.candidate_count AS related_settlement_candidates,
    related_settlement.same_store_candidate_count
        AS related_settlement_same_store_candidates,
    related_settlement.same_store_sales_settlement_id
        AS related_same_store_sales_settlement_id,
    related_settlement.same_store_settlement_order_id
        AS related_same_store_settlement_order_id,
    adjustment_settlement.candidate_count
        AS adjustment_settlement_candidates,
    adjustment_settlement.same_store_candidate_count
        AS adjustment_settlement_same_store_candidates,
    adjustment_settlement.same_store_sales_settlement_id
        AS adjustment_same_store_sales_settlement_id,
    adjustment_settlement.same_store_settlement_order_id
        AS adjustment_same_store_settlement_order_id,
    adjustment_order.candidate_count AS adjustment_order_candidates,
    adjustment_order.same_store_candidate_count
        AS adjustment_order_same_store_candidates,
    adjustment_order.same_store_sales_order_id
        AS adjustment_order_same_store_sales_order_id,
    CASE
        WHEN adjustment_settlement.same_store_candidate_count = 1
            THEN 'unique_settlement_via_adjustment_id'
        WHEN related_settlement.same_store_candidate_count = 1
            THEN 'unique_settlement_via_related_order_id'
        WHEN related_order.same_store_candidate_count = 1
            THEN 'unique_order_via_related_order_id'
        WHEN adjustment_order.same_store_candidate_count = 1
            THEN 'unique_order_via_adjustment_id'
        WHEN adjustment_settlement.candidate_count > 0
          OR related_settlement.candidate_count > 0
          OR related_order.candidate_count > 0
          OR adjustment_order.candidate_count > 0
            THEN 'candidate_conflict_or_cross_store'
        ELSE 'no_candidate'
    END AS resolution_class
FROM tmp_tiktok_adjustment_target target
JOIN related_order_match related_order USING (sales_settlement_adjustment_id)
JOIN related_settlement_match related_settlement
  USING (sales_settlement_adjustment_id)
JOIN adjustment_settlement_match adjustment_settlement
  USING (sales_settlement_adjustment_id)
JOIN adjustment_order_match adjustment_order
  USING (sales_settlement_adjustment_id);

ANALYZE tmp_tiktok_candidate_summary;

-- A. Main resolution answer.
SELECT
    resolution_class,
    COUNT(*) AS adjustment_rows,
    COUNT(DISTINCT external_adjustment_id) AS adjustment_ids,
    COUNT(DISTINCT related_external_order_id) AS related_order_ids,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount,
    MIN(adjustment_occurred_at) AS min_adjustment_at,
    MAX(adjustment_occurred_at) AS max_adjustment_at
FROM tmp_tiktok_candidate_summary
GROUP BY resolution_class
ORDER BY adjustment_rows DESC, resolution_class;

-- B. Candidate mechanism by store and month.
SELECT
    DATE_TRUNC('month', adjustment_occurred_at)::date AS adjustment_month,
    store_id,
    store_code,
    resolution_class,
    COUNT(*) AS adjustment_rows,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount
FROM tmp_tiktok_candidate_summary
GROUP BY 1, 2, 3, 4
ORDER BY 1, 3, 4;

-- C. ID-shape profile. This helps confirm whether related_order_id and
-- order_adjustment_id belong to different identity domains.
SELECT
    resolution_class,
    LENGTH(external_adjustment_id) AS adjustment_id_length,
    LENGTH(related_external_order_id) AS related_order_id_length,
    COUNT(*) AS adjustment_rows,
    COUNT(*) FILTER (
        WHERE external_adjustment_id = related_external_order_id
    ) AS identical_source_ids,
    MIN(external_adjustment_id) AS sample_adjustment_id,
    MIN(related_external_order_id) AS sample_related_order_id
FROM tmp_tiktok_candidate_summary
GROUP BY 1, 2, 3
ORDER BY adjustment_rows DESC, 1, 2, 3;

-- D. Samples of rows that cannot be resolved uniquely.
SELECT
    sales_settlement_adjustment_id,
    store_id,
    store_code,
    external_adjustment_id,
    related_external_order_id,
    raw_transaction_type,
    signed_adjustment_amount,
    adjustment_occurred_at,
    related_order_candidates,
    related_order_same_store_candidates,
    related_settlement_candidates,
    related_settlement_same_store_candidates,
    adjustment_settlement_candidates,
    adjustment_settlement_same_store_candidates,
    adjustment_order_candidates,
    adjustment_order_same_store_candidates,
    resolution_class,
    source_file,
    source_row_number
FROM tmp_tiktok_candidate_summary
WHERE resolution_class IN ('candidate_conflict_or_cross_store', 'no_candidate')
ORDER BY ABS(signed_adjustment_amount) DESC,
         sales_settlement_adjustment_id
LIMIT 100;

ROLLBACK;
