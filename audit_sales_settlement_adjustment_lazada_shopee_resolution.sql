-- Diagnose the remaining Lazada and Shopee settlement-adjustment linkage gaps.
-- Read-only: this audit does not update production facts.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_adjustment_target ON COMMIT DROP AS
SELECT
    adjustment.sales_settlement_adjustment_id,
    adjustment.source_system,
    adjustment.store_id,
    store.store_code,
    store.store_name,
    adjustment.sales_order_id,
    adjustment.sales_settlement_id,
    adjustment.external_adjustment_id,
    NULLIF(BTRIM(adjustment.related_external_order_id), '')
        AS related_external_order_id,
    LOWER(REGEXP_REPLACE(
        COALESCE(adjustment.related_external_order_id, ''),
        '[^a-zA-Z0-9]+',
        '',
        'g'
    )) AS normalized_related_order_id,
    adjustment.adjustment_scope,
    adjustment.raw_transaction_type,
    adjustment.raw_adjustment_name,
    adjustment.signed_adjustment_amount,
    adjustment.adjustment_occurred_at,
    adjustment.source_file,
    adjustment.source_sheet,
    adjustment.source_row_number,
    adjustment.raw_record_id
FROM public.fact_sales_settlement_adjustment adjustment
LEFT JOIN public.dim_store store
  ON store.store_id = adjustment.store_id
WHERE adjustment.is_active = TRUE
  AND adjustment.source_system IN ('lazada', 'shopee')
  AND (
      (adjustment.source_system = 'lazada'
       AND adjustment.sales_order_id IS NULL
       AND adjustment.sales_settlement_id IS NULL)
      OR
      (adjustment.source_system = 'shopee'
       AND adjustment.sales_order_id IS NULL
       AND adjustment.sales_settlement_id IS NULL
       AND NULLIF(BTRIM(adjustment.related_external_order_id), '') IS NOT NULL)
      OR
      (adjustment.source_system = 'shopee'
       AND adjustment.sales_order_id IS NULL
       AND adjustment.sales_settlement_id IS NOT NULL)
  );

ANALYZE tmp_adjustment_target;

CREATE TEMP TABLE tmp_order_candidate ON COMMIT DROP AS
SELECT
    target.sales_settlement_adjustment_id,
    orders.sales_order_id AS candidate_sales_order_id,
    orders.external_order_id AS candidate_external_order_id,
    orders.store_id AS candidate_store_id,
    CASE
        WHEN target.related_external_order_id = orders.external_order_id
         AND target.store_id = orders.store_id
            THEN 'exact_source_store_order_id'
        WHEN target.normalized_related_order_id = LOWER(REGEXP_REPLACE(
                 orders.external_order_id, '[^a-zA-Z0-9]+', '', 'g'
             ))
         AND target.store_id = orders.store_id
            THEN 'normalized_source_store_order_id'
        WHEN target.related_external_order_id = orders.external_order_id
            THEN 'exact_source_order_id_other_store'
        ELSE 'normalized_source_order_id_other_store'
    END AS match_method
FROM tmp_adjustment_target target
JOIN public.fact_sales_order orders
  ON orders.source_system = target.source_system
 AND orders.sales_channel_type = 'online'
 AND orders.is_active = TRUE
 AND (
      target.related_external_order_id = orders.external_order_id
      OR (
          target.normalized_related_order_id <> ''
          AND target.normalized_related_order_id = LOWER(REGEXP_REPLACE(
              orders.external_order_id, '[^a-zA-Z0-9]+', '', 'g'
          ))
      )
 );

CREATE TEMP TABLE tmp_settlement_candidate ON COMMIT DROP AS
SELECT
    target.sales_settlement_adjustment_id,
    settlement.sales_settlement_id AS candidate_sales_settlement_id,
    settlement.sales_order_id AS settlement_sales_order_id,
    settlement.external_order_id AS candidate_external_order_id,
    settlement.store_id AS candidate_store_id,
    CASE
        WHEN target.related_external_order_id = settlement.external_order_id
         AND target.store_id = settlement.store_id
            THEN 'exact_source_store_order_id'
        WHEN target.normalized_related_order_id = LOWER(REGEXP_REPLACE(
                 settlement.external_order_id, '[^a-zA-Z0-9]+', '', 'g'
             ))
         AND target.store_id = settlement.store_id
            THEN 'normalized_source_store_order_id'
        WHEN target.related_external_order_id = settlement.external_order_id
            THEN 'exact_source_order_id_other_store'
        ELSE 'normalized_source_order_id_other_store'
    END AS match_method
FROM tmp_adjustment_target target
JOIN public.fact_sales_settlement settlement
  ON settlement.source_system = target.source_system
 AND settlement.sales_channel_type = 'online'
 AND settlement.is_active = TRUE
 AND (
      target.related_external_order_id = settlement.external_order_id
      OR (
          target.normalized_related_order_id <> ''
          AND target.normalized_related_order_id = LOWER(REGEXP_REPLACE(
              settlement.external_order_id, '[^a-zA-Z0-9]+', '', 'g'
          ))
      )
 );

-- A. Lazada rows expected to remain at store/month grain.
SELECT
    sales_settlement_adjustment_id,
    store_id,
    store_code,
    store_name,
    external_adjustment_id,
    related_external_order_id,
    raw_adjustment_name,
    signed_adjustment_amount,
    adjustment_occurred_at,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id
FROM tmp_adjustment_target
WHERE source_system = 'lazada'
ORDER BY adjustment_occurred_at, sales_settlement_adjustment_id;

-- B. Shopee gaps with candidate counts. A safe automatic repair requires one
-- same-store order candidate and at most one compatible settlement candidate.
SELECT
    target.sales_settlement_adjustment_id,
    target.store_id,
    target.store_code,
    target.related_external_order_id,
    target.sales_settlement_id AS current_sales_settlement_id,
    target.raw_adjustment_name,
    target.signed_adjustment_amount,
    target.adjustment_occurred_at,
    COUNT(DISTINCT order_candidate.candidate_sales_order_id) AS order_candidates,
    COUNT(DISTINCT order_candidate.candidate_sales_order_id) FILTER (
        WHERE order_candidate.candidate_store_id = target.store_id
    ) AS same_store_order_candidates,
    COUNT(DISTINCT settlement_candidate.candidate_sales_settlement_id)
        AS settlement_candidates,
    COUNT(DISTINCT settlement_candidate.candidate_sales_settlement_id) FILTER (
        WHERE settlement_candidate.candidate_store_id = target.store_id
    ) AS same_store_settlement_candidates,
    STRING_AGG(
        DISTINCT order_candidate.match_method || ':' ||
        order_candidate.candidate_sales_order_id::text,
        ' | '
    ) AS order_candidate_detail,
    STRING_AGG(
        DISTINCT settlement_candidate.match_method || ':' ||
        settlement_candidate.candidate_sales_settlement_id::text,
        ' | '
    ) AS settlement_candidate_detail
FROM tmp_adjustment_target target
LEFT JOIN tmp_order_candidate order_candidate
  ON order_candidate.sales_settlement_adjustment_id =
     target.sales_settlement_adjustment_id
LEFT JOIN tmp_settlement_candidate settlement_candidate
  ON settlement_candidate.sales_settlement_adjustment_id =
     target.sales_settlement_adjustment_id
WHERE target.source_system = 'shopee'
GROUP BY
    target.sales_settlement_adjustment_id,
    target.store_id,
    target.store_code,
    target.related_external_order_id,
    target.sales_settlement_id,
    target.raw_adjustment_name,
    target.signed_adjustment_amount,
    target.adjustment_occurred_at
ORDER BY target.sales_settlement_adjustment_id;

-- C. Detail of the three settlement-linked rows whose settlement currently
-- has no resolved order.
SELECT
    target.sales_settlement_adjustment_id,
    target.sales_settlement_id,
    settlement.external_order_id AS settlement_external_order_id,
    settlement.store_id AS settlement_store_id,
    settlement.sales_order_id AS settlement_sales_order_id,
    target.related_external_order_id,
    target.raw_adjustment_name,
    target.signed_adjustment_amount,
    target.adjustment_occurred_at,
    target.source_file,
    target.source_row_number
FROM tmp_adjustment_target target
JOIN public.fact_sales_settlement settlement
  ON settlement.sales_settlement_id = target.sales_settlement_id
WHERE target.source_system = 'shopee'
  AND target.sales_order_id IS NULL
  AND target.sales_settlement_id IS NOT NULL
  AND settlement.sales_order_id IS NULL
ORDER BY target.sales_settlement_adjustment_id;

ROLLBACK;
