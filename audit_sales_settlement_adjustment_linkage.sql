-- Audit whether active settlement adjustments can be attributed to an order,
-- a settlement, only a store/period, or remain unresolved.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_adjustment_linkage ON COMMIT DROP AS
SELECT
    adjustment.sales_settlement_adjustment_id,
    adjustment.source_system,
    adjustment.adjustment_scope,
    adjustment.fee_type_id,
    fee_type.fee_code,
    fee_type.fee_name,
    adjustment.store_id,
    adjustment.sales_order_id AS direct_sales_order_id,
    adjustment.sales_settlement_id,
    settlement.sales_order_id AS settlement_sales_order_id,
    COALESCE(
        adjustment.sales_order_id,
        settlement.sales_order_id
    ) AS resolved_sales_order_id,
    NULLIF(BTRIM(adjustment.related_external_order_id), '')
        AS related_external_order_id,
    adjustment.adjustment_occurred_at,
    adjustment.signed_adjustment_amount,
    CASE
        WHEN adjustment.sales_order_id IS NOT NULL
         AND adjustment.sales_settlement_id IS NOT NULL
            THEN 'order_and_settlement'
        WHEN adjustment.sales_order_id IS NOT NULL
            THEN 'order_only'
        WHEN adjustment.sales_settlement_id IS NOT NULL
            THEN 'settlement_only'
        WHEN NULLIF(BTRIM(adjustment.related_external_order_id), '') IS NOT NULL
            THEN 'source_order_id_unlinked'
        WHEN adjustment.store_id IS NOT NULL
         AND adjustment.adjustment_occurred_at IS NOT NULL
            THEN 'store_period_only'
        ELSE 'unresolved'
    END AS linkage_status
FROM public.fact_sales_settlement_adjustment adjustment
LEFT JOIN public.fact_sales_settlement settlement
  ON settlement.sales_settlement_id = adjustment.sales_settlement_id
LEFT JOIN public.fee_type fee_type
  ON fee_type.fee_type_id = adjustment.fee_type_id
WHERE adjustment.is_active = TRUE;

ANALYZE tmp_adjustment_linkage;

-- A. Overall answer by marketplace. `linked_to_resolved_order` includes orders
-- reached indirectly through a linked settlement.
SELECT
    source_system,
    COUNT(*) AS total_adjustment_rows,
    COUNT(*) FILTER (
        WHERE direct_sales_order_id IS NOT NULL
    ) AS directly_linked_order_rows,
    COUNT(*) FILTER (
        WHERE sales_settlement_id IS NOT NULL
    ) AS linked_settlement_rows,
    COUNT(*) FILTER (
        WHERE resolved_sales_order_id IS NOT NULL
    ) AS linked_to_resolved_order_rows,
    COUNT(*) FILTER (
        WHERE direct_sales_order_id IS NOT NULL
           OR sales_settlement_id IS NOT NULL
    ) AS linked_order_or_settlement_rows,
    COUNT(*) FILTER (
        WHERE direct_sales_order_id IS NULL
          AND sales_settlement_id IS NULL
    ) AS without_order_or_settlement_link_rows,
    COUNT(*) FILTER (
        WHERE linkage_status = 'source_order_id_unlinked'
    ) AS source_order_id_unlinked_rows,
    COUNT(*) FILTER (
        WHERE linkage_status = 'store_period_only'
    ) AS store_period_only_rows,
    COUNT(*) FILTER (
        WHERE linkage_status = 'unresolved'
    ) AS unresolved_rows,
    SUM(signed_adjustment_amount) AS total_signed_adjustment_amount,
    SUM(signed_adjustment_amount) FILTER (
        WHERE direct_sales_order_id IS NOT NULL
           OR sales_settlement_id IS NOT NULL
    ) AS linked_signed_adjustment_amount,
    SUM(signed_adjustment_amount) FILTER (
        WHERE direct_sales_order_id IS NULL
          AND sales_settlement_id IS NULL
    ) AS unlinked_signed_adjustment_amount
FROM tmp_adjustment_linkage
GROUP BY source_system
ORDER BY source_system;

-- B. Mutually exclusive linkage buckets and their monetary values.
SELECT
    source_system,
    linkage_status,
    COUNT(*) AS adjustment_rows,
    COUNT(DISTINCT resolved_sales_order_id) AS resolved_orders,
    COUNT(DISTINCT sales_settlement_id) AS settlements,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount,
    MIN(adjustment_occurred_at) AS min_adjustment_at,
    MAX(adjustment_occurred_at) AS max_adjustment_at
FROM tmp_adjustment_linkage
GROUP BY source_system, linkage_status
ORDER BY source_system, linkage_status;

-- C. Unlinked rows by governed fee type. This shows what can remain at
-- store/month grain and what still needs linkage or classification work.
SELECT
    source_system,
    linkage_status,
    fee_type_id,
    fee_code,
    fee_name,
    COUNT(*) AS adjustment_rows,
    COUNT(*) FILTER (WHERE store_id IS NOT NULL) AS rows_with_store,
    COUNT(*) FILTER (
        WHERE adjustment_occurred_at IS NOT NULL
    ) AS rows_with_business_date,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount
FROM tmp_adjustment_linkage
WHERE direct_sales_order_id IS NULL
  AND sales_settlement_id IS NULL
GROUP BY
    source_system,
    linkage_status,
    fee_type_id,
    fee_code,
    fee_name
ORDER BY
    source_system,
    linkage_status,
    ABS(SUM(signed_adjustment_amount)) DESC,
    fee_code;

-- D. Referential and classification guardrails. Every value should be zero.
SELECT
    COUNT(*) FILTER (
        WHERE sales_settlement_id IS NOT NULL
          AND settlement_sales_order_id IS NULL
          AND direct_sales_order_id IS NULL
    ) AS linked_settlement_without_resolved_order,
    COUNT(*) FILTER (
        WHERE direct_sales_order_id IS NOT NULL
          AND settlement_sales_order_id IS NOT NULL
          AND direct_sales_order_id <> settlement_sales_order_id
    ) AS order_settlement_mismatch_rows,
    COUNT(*) FILTER (
        WHERE linkage_status = 'store_period_only'
          AND (store_id IS NULL OR adjustment_occurred_at IS NULL)
    ) AS invalid_store_period_rows
FROM tmp_adjustment_linkage;

ROLLBACK;
