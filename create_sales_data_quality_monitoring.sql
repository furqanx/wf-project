-- Automated data-quality checks for canonical and semantic Sales datasets.
--
-- Each row is one check. A zero issue_count means the check passed.
-- Safe to rerun; no source data is modified.

BEGIN;

CREATE OR REPLACE VIEW public.vw_sales_data_quality_monitor AS
WITH
duplicate_orders AS (
    SELECT COUNT(*) AS issue_count
    FROM (
        SELECT sales_order_id
        FROM public.vw_sales_order_summary
        GROUP BY sales_order_id
        HAVING COUNT(*) > 1
    ) duplicates
),
duplicate_items AS (
    SELECT COUNT(*) AS issue_count
    FROM (
        SELECT
            sales_order_id,
            COALESCE(source_line_id, ''),
            COALESCE(source_sku_code, ''),
            COALESCE(source_product_name, ''),
            COALESCE(source_row_number, -1)
        FROM public.vw_sales_order_item_analytics
        GROUP BY
            sales_order_id,
            COALESCE(source_line_id, ''),
            COALESCE(source_sku_code, ''),
            COALESCE(source_product_name, ''),
            COALESCE(source_row_number, -1)
        HAVING COUNT(*) > 1
    ) duplicates
),
orders_without_items AS (
    SELECT COUNT(*) AS issue_count
    FROM public.vw_sales_semantic_order
    WHERE valid_order_count = 1
      AND item_rows = 0
),
items_without_product AS (
    SELECT COUNT(*) AS issue_count
    FROM public.vw_sales_order_item_analytics
    WHERE product_id IS NULL
       OR product_sku_alias_id IS NULL
),
invalid_order_dates AS (
    SELECT COUNT(*) AS issue_count
    FROM public.vw_sales_order_summary
    WHERE order_date IS NULL
       OR order_date > CURRENT_DATE
),
invalid_item_quantities AS (
    SELECT COUNT(*) AS issue_count
    FROM public.vw_sales_order_item_analytics
    WHERE quantity IS NULL
       OR quantity <= 0
),
order_item_amount_differences AS (
    SELECT
        COUNT(*) AS issue_count,
        COALESCE(SUM(ABS(item_to_order_amount_delta)), 0) AS issue_amount
    FROM public.vw_sales_order_summary
    WHERE ABS(item_to_order_amount_delta) > 0.01
),
accurate_online_included AS (
    SELECT COUNT(*) AS issue_count
    FROM public.vw_sales_order_analytics
    WHERE source_system = 'accurate'
      AND analytics_channel_type = 'online'
),
accurate_unclassified AS (
    SELECT COUNT(*) AS issue_count
    FROM public.vw_sales_order_channel_classification
    WHERE analytics_exclusion_reason = 'accurate_offline_unclassified'
),
marketplace_duplicate_included AS (
    SELECT COUNT(*) AS issue_count
    FROM (
        SELECT
            source_system,
            external_order_id,
            COALESCE(net_order_amount, 0),
            product_quantity_signature
        FROM public.vw_sales_order_analytics
        WHERE source_system IN ('shopee', 'lazada', 'tiktok_tokopedia')
        GROUP BY
            source_system,
            external_order_id,
            COALESCE(net_order_amount, 0),
            product_quantity_signature
        HAVING COUNT(*) > 1
    ) duplicates
),
semantic_order_reconciliation AS (
    SELECT
        ABS(
            (SELECT COUNT(*) FROM public.vw_sales_semantic_order)
            - (SELECT COUNT(*) FROM public.vw_sales_order_summary)
        ) AS order_row_delta,
        ABS(
            COALESCE((SELECT SUM(booked_revenue) FROM public.vw_sales_semantic_order), 0)
            - COALESCE((SELECT SUM(order_revenue) FROM public.vw_sales_order_summary), 0)
        ) AS revenue_delta
),
semantic_rollup_reconciliation AS (
    SELECT
        ABS(
            COALESCE((SELECT SUM(canonical_order_count) FROM public.vw_sales_semantic_daily), 0)
            - COALESCE((SELECT SUM(canonical_order_count) FROM public.vw_sales_semantic_order), 0)
        ) + ABS(
            COALESCE((SELECT SUM(canonical_order_count) FROM public.vw_sales_semantic_monthly), 0)
            - COALESCE((SELECT SUM(canonical_order_count) FROM public.vw_sales_semantic_order), 0)
        ) AS order_row_delta,
        ABS(
            COALESCE((SELECT SUM(recognized_revenue) FROM public.vw_sales_semantic_daily), 0)
            - COALESCE((SELECT SUM(recognized_revenue) FROM public.vw_sales_semantic_order), 0)
        ) + ABS(
            COALESCE((SELECT SUM(recognized_revenue) FROM public.vw_sales_semantic_monthly), 0)
            - COALESCE((SELECT SUM(recognized_revenue) FROM public.vw_sales_semantic_order), 0)
        ) AS revenue_delta
),
semantic_rule_violations AS (
    SELECT COUNT(*) AS issue_count
    FROM public.vw_sales_semantic_order
    WHERE (is_canceled AND (
              valid_order_count <> 0
           OR recognized_revenue <> 0
           OR recognized_units_sold <> 0
          ))
       OR (NOT is_canceled AND recognized_revenue <> order_revenue)
       OR (analytics_channel_type <> 'online' AND fulfillment_eligible_order_count <> 0)
)
SELECT
    'canonical_order_duplicate'::text AS check_name,
    'critical'::text AS severity,
    issue_count::bigint,
    NULL::numeric AS issue_amount,
    'vw_sales_order_summary must contain one row per sales_order_id.'::text AS description
FROM duplicate_orders
UNION ALL
SELECT
    'canonical_item_duplicate', 'critical', issue_count::bigint, NULL::numeric,
    'Canonical order-item business grain must be unique.'
FROM duplicate_items
UNION ALL
SELECT
    'valid_order_without_item', 'critical', issue_count::bigint, NULL::numeric,
    'Every valid canonical order must contain at least one item.'
FROM orders_without_items
UNION ALL
SELECT
    'item_without_product_mapping', 'critical', issue_count::bigint, NULL::numeric,
    'Every canonical item must resolve to product_id and product_sku_alias_id.'
FROM items_without_product
UNION ALL
SELECT
    'invalid_order_date', 'critical', issue_count::bigint, NULL::numeric,
    'Canonical order_date must be present and must not be in the future.'
FROM invalid_order_dates
UNION ALL
SELECT
    'invalid_item_quantity', 'critical', issue_count::bigint, NULL::numeric,
    'Canonical sales item quantity must be positive.'
FROM invalid_item_quantities
UNION ALL
SELECT
    'order_item_amount_difference', 'warning', issue_count::bigint, issue_amount,
    'Header revenue is authoritative; item/header differences remain visible for source review.'
FROM order_item_amount_differences
UNION ALL
SELECT
    'accurate_online_included', 'critical', issue_count::bigint, NULL::numeric,
    'Accurate marketplace-like records must never enter analytical online sales.'
FROM accurate_online_included
UNION ALL
SELECT
    'accurate_offline_unclassified', 'warning', issue_count::bigint, NULL::numeric,
    'Accurate non-marketplace records require an explicit B2B or retail classification.'
FROM accurate_unclassified
UNION ALL
SELECT
    'marketplace_duplicate_included', 'critical', issue_count::bigint, NULL::numeric,
    'Exact marketplace duplicates must be reduced to one canonical transaction.'
FROM marketplace_duplicate_included
UNION ALL
SELECT
    'semantic_order_reconciliation',
    'critical',
    (order_row_delta + CASE WHEN revenue_delta > 0.01 THEN 1 ELSE 0 END)::bigint,
    revenue_delta,
    'Semantic order rows and booked revenue must reconcile to the analytical order summary.'
FROM semantic_order_reconciliation
UNION ALL
SELECT
    'semantic_rollup_reconciliation',
    'critical',
    (order_row_delta + CASE WHEN revenue_delta > 0.01 THEN 1 ELSE 0 END)::bigint,
    revenue_delta,
    'Daily and monthly semantic rollups must reconcile to the order-grain semantic view.'
FROM semantic_rollup_reconciliation
UNION ALL
SELECT
    'semantic_rule_violation', 'critical', issue_count::bigint, NULL::numeric,
    'Canceled-order, valid-revenue, and offline-fulfillment semantic rules must hold.'
FROM semantic_rule_violations;

COMMENT ON VIEW public.vw_sales_data_quality_monitor IS
'Current Sales analytics and semantic-layer data-quality checks. issue_count=0 means pass.';

COMMIT;

