-- Read-only readiness audit for the Sales profitability serving layer.
--
-- Goals:
-- - establish coverage and date ranges for revenue, settlement, fee,
--   adjustment, return, and wallet sources;
-- - verify that marketplace costs can be linked to canonical orders/stores;
-- - identify which costs can be allocated to products without estimation;
-- - discover candidate Ads, COGS, and other cost sources.

\pset pager off
\set ON_ERROR_STOP on

SET statement_timeout = '10min';
SET lock_timeout = '10s';

-- 1. Online order coverage. Accurate rows are shown deliberately because they
-- must not become profitability revenue when a direct marketplace row exists.
SELECT
    source_system,
    sales_channel_type,
    COUNT(*) FILTER (WHERE is_active) AS active_rows,
    COUNT(DISTINCT external_order_id) FILTER (WHERE is_active) AS active_order_ids,
    MIN(order_date) FILTER (WHERE is_active) AS min_order_date,
    MAX(order_date) FILTER (WHERE is_active) AS max_order_date,
    SUM(net_order_amount) FILTER (WHERE is_active) AS active_net_order_amount
FROM public.fact_sales_order
WHERE sales_channel_type = 'online'
   OR source_system IN ('shopee', 'lazada', 'tiktok_tokopedia')
GROUP BY source_system, sales_channel_type
ORDER BY source_system, sales_channel_type;

-- 2. Settlement coverage, monetary completeness, and order linkage.
SELECT
    source_system,
    COUNT(*) FILTER (WHERE is_active) AS settlement_rows,
    COUNT(DISTINCT external_order_id) FILTER (WHERE is_active) AS settlement_order_ids,
    COUNT(*) FILTER (WHERE is_active AND sales_order_id IS NOT NULL) AS linked_rows,
    COUNT(*) FILTER (WHERE is_active AND sales_order_id IS NULL) AS unlinked_rows,
    COUNT(*) FILTER (
        WHERE is_active
          AND COALESCE(released_at, settled_at, order_created_at) IS NULL
    ) AS rows_without_business_date,
    MIN(COALESCE(released_at, settled_at, order_created_at)) FILTER (WHERE is_active) AS min_business_at,
    MAX(COALESCE(released_at, settled_at, order_created_at)) FILTER (WHERE is_active) AS max_business_at,
    SUM(gross_revenue_amount) FILTER (WHERE is_active) AS gross_revenue_amount,
    SUM(refund_amount) FILTER (WHERE is_active) AS refund_amount,
    SUM(total_fee_amount) FILTER (WHERE is_active) AS total_fee_amount,
    SUM(settlement_amount) FILTER (WHERE is_active) AS settlement_amount
FROM public.fact_sales_settlement
GROUP BY source_system
ORDER BY source_system;

-- 3. Coverage of canonical direct-marketplace orders by settlement records.
WITH direct_orders AS (
    SELECT sales_order_id, source_system, external_order_id, net_order_amount
    FROM public.vw_sales_order_analytics
    WHERE source_system IN ('shopee', 'lazada', 'tiktok_tokopedia')
), settlement_orders AS (
    SELECT DISTINCT sales_order_id
    FROM public.fact_sales_settlement
    WHERE is_active = TRUE
      AND sales_order_id IS NOT NULL
)
SELECT
    orders.source_system,
    COUNT(*) AS canonical_orders,
    COUNT(settlements.sales_order_id) AS orders_with_settlement,
    COUNT(*) - COUNT(settlements.sales_order_id) AS orders_without_settlement,
    ROUND(
        100.0 * COUNT(settlements.sales_order_id) / NULLIF(COUNT(*), 0),
        2
    ) AS settlement_coverage_pct,
    SUM(orders.net_order_amount) AS canonical_revenue,
    SUM(orders.net_order_amount) FILTER (
        WHERE settlements.sales_order_id IS NULL
    ) AS revenue_without_settlement
FROM direct_orders orders
LEFT JOIN settlement_orders settlements
    ON settlements.sales_order_id = orders.sales_order_id
GROUP BY orders.source_system
ORDER BY orders.source_system;

-- 4. Fee coverage by governed category. Low-confidence and review-required
-- rows must not enter official profitability until reviewed.
SELECT
    fees.source_system,
    types.fee_category,
    types.is_platform_fee,
    COUNT(*) AS fee_rows,
    COUNT(*) FILTER (WHERE fees.sales_order_id IS NOT NULL) AS linked_order_rows,
    COUNT(*) FILTER (WHERE fees.sales_settlement_id IS NOT NULL) AS linked_settlement_rows,
    COUNT(*) FILTER (WHERE fees.sign_confidence = 'low') AS low_confidence_rows,
    COUNT(*) FILTER (WHERE fees.sign_rule = 'review_required') AS review_required_rows,
    SUM(fees.signed_fee_amount) AS signed_fee_amount
FROM public.fact_sales_settlement_fee_detail fees
JOIN public.fee_type types
    ON types.fee_type_id = fees.fee_type_id
WHERE fees.is_active = TRUE
GROUP BY fees.source_system, types.fee_category, types.is_platform_fee
ORDER BY fees.source_system, types.fee_category, types.is_platform_fee;

-- 5. Fee grain determines whether a cost can be attributed directly to a SKU.
SELECT
    source_system,
    fee_grain_type,
    COUNT(*) AS fee_rows,
    COUNT(*) FILTER (WHERE sales_order_id IS NOT NULL) AS linked_order_rows,
    COUNT(*) FILTER (WHERE source_sku_code IS NOT NULL) AS rows_with_source_sku,
    COUNT(*) FILTER (
        WHERE sales_order_id IS NOT NULL AND source_sku_code IS NOT NULL
    ) AS directly_product_allocatable_rows,
    SUM(signed_fee_amount) AS signed_fee_amount
FROM public.fact_sales_settlement_fee_detail
WHERE is_active = TRUE
GROUP BY source_system, fee_grain_type
ORDER BY source_system, fee_grain_type;

-- 6. Confirm that item/SKU fee rows resolve to exactly one active sales item.
WITH fee_item_match AS (
    SELECT
        fees.sales_settlement_fee_detail_id,
        fees.source_system,
        fees.signed_fee_amount,
        COUNT(items.sales_order_item_id) AS matched_item_rows
    FROM public.fact_sales_settlement_fee_detail fees
    LEFT JOIN public.fact_sales_order_item items
        ON items.sales_order_id = fees.sales_order_id
       AND items.source_sku_code = fees.source_sku_code
    WHERE fees.is_active = TRUE
      AND fees.sales_order_id IS NOT NULL
      AND fees.source_sku_code IS NOT NULL
    GROUP BY
        fees.sales_settlement_fee_detail_id,
        fees.source_system,
        fees.signed_fee_amount
)
SELECT
    source_system,
    COUNT(*) AS candidate_fee_rows,
    COUNT(*) FILTER (WHERE matched_item_rows = 1) AS exact_item_matches,
    COUNT(*) FILTER (WHERE matched_item_rows = 0) AS unmatched_item_rows,
    COUNT(*) FILTER (WHERE matched_item_rows > 1) AS ambiguous_item_rows,
    SUM(signed_fee_amount) FILTER (WHERE matched_item_rows <> 1) AS non_exact_amount
FROM fee_item_match
GROUP BY source_system
ORDER BY source_system;

-- 7. Adjustment coverage and governed classification.
SELECT
    adjustments.source_system,
    adjustments.adjustment_scope,
    types.fee_category,
    COUNT(*) AS adjustment_rows,
    COUNT(*) FILTER (WHERE adjustments.sales_order_id IS NOT NULL) AS linked_order_rows,
    COUNT(*) FILTER (WHERE adjustments.sales_settlement_id IS NOT NULL) AS linked_settlement_rows,
    COUNT(*) FILTER (WHERE adjustments.adjustment_occurred_at IS NULL) AS rows_without_business_date,
    COUNT(*) FILTER (WHERE adjustments.sign_confidence = 'low') AS low_confidence_rows,
    COUNT(*) FILTER (WHERE adjustments.sign_rule = 'review_required') AS review_required_rows,
    SUM(adjustments.signed_adjustment_amount) AS signed_adjustment_amount
FROM public.fact_sales_settlement_adjustment adjustments
JOIN public.fee_type types
    ON types.fee_type_id = adjustments.fee_type_id
WHERE adjustments.is_active = TRUE
GROUP BY
    adjustments.source_system,
    adjustments.adjustment_scope,
    types.fee_category
ORDER BY
    adjustments.source_system,
    adjustments.adjustment_scope,
    types.fee_category;

-- 8. Wallet rows that may represent Ads, penalties, or other profitability
-- costs. These remain candidates until their classification is approved.
SELECT
    source_system,
    CASE
        WHEN CONCAT_WS(' ', transaction_type, transaction_sub_type, transaction_description)
             ~* '(iklan|ads?|advert|campaign)' THEN 'ads_candidate'
        WHEN CONCAT_WS(' ', transaction_type, transaction_sub_type, transaction_description)
             ~* '(penalt|denda|fine)' THEN 'penalty_candidate'
        WHEN movement_direction = 'debit' THEN 'other_debit'
        WHEN movement_direction = 'credit' THEN 'credit'
        ELSE 'zero_or_unknown'
    END AS profitability_candidate,
    COUNT(*) AS transaction_rows,
    COUNT(*) FILTER (WHERE sales_order_id IS NOT NULL) AS linked_order_rows,
    COUNT(*) FILTER (WHERE transaction_occurred_at IS NULL) AS rows_without_business_date,
    MIN(transaction_occurred_at) AS min_transaction_at,
    MAX(transaction_occurred_at) AS max_transaction_at,
    SUM(signed_amount) AS signed_amount
FROM public.fact_balance_transaction
WHERE is_active = TRUE
GROUP BY source_system, profitability_candidate
ORDER BY source_system, profitability_candidate;

-- 9. Returns/refunds available for profitability. A zero monetary value with
-- non-zero returned quantity is a source limitation, not a zero-cost return.
WITH return_items AS (
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
    COUNT(*) AS return_rows,
    COUNT(*) FILTER (WHERE returns.sales_order_id IS NOT NULL) AS linked_order_rows,
    SUM(COALESCE(items.return_qty, 0)) AS return_qty,
    SUM(COALESCE(returns.refund_amount, 0)) AS header_refund_amount,
    SUM(COALESCE(items.item_refund_amount, 0)) AS item_refund_amount,
    COUNT(*) FILTER (
        WHERE COALESCE(items.return_qty, 0) > 0
          AND COALESCE(returns.refund_amount, 0) = 0
          AND COALESCE(items.item_refund_amount, 0) = 0
    ) AS rows_without_refund_value
FROM public.fact_sales_return returns
LEFT JOIN return_items items
    ON items.sales_return_id = returns.sales_return_id
WHERE returns.is_active = TRUE
GROUP BY returns.source_system, returns.return_type
ORDER BY returns.source_system, returns.return_type;

-- 10. Candidate physical sources for Ads, COGS, product cost, credible cost,
-- and inventory valuation. This is discovery only; names do not establish
-- semantic suitability.
SELECT
    table_schema,
    table_name,
    table_type
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND table_name ~* '(cogs|cost|biaya|ads|advert|campaign|price|inventory|production)'
ORDER BY table_schema, table_name;

-- 11. Candidate monetary columns in those sources.
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND (
      table_name ~* '(cogs|cost|biaya|ads|advert|campaign|price|inventory|production)'
      OR column_name ~* '(cogs|cost|biaya|ads|advert|campaign|price|amount)'
  )
  AND data_type IN (
      'smallint', 'integer', 'bigint', 'numeric', 'decimal',
      'real', 'double precision', 'money'
  )
ORDER BY table_schema, table_name, ordinal_position;

-- 12. Existing monthly money-flow coverage. Null months or critical issues are
-- blockers for publishing official profitability metrics.
SELECT
    source_system,
    MIN(period_month) AS min_period_month,
    MAX(period_month) AS max_period_month,
    COUNT(*) AS source_store_month_rows,
    SUM(order_rows) AS order_rows,
    SUM(net_order_amount) AS net_order_amount,
    SUM(settlement_rows) AS settlement_rows,
    SUM(settlement_amount) AS settlement_amount,
    SUM(fee_detail_rows) AS fee_detail_rows,
    SUM(signed_fee_amount) AS signed_fee_amount,
    SUM(adjustment_rows) AS adjustment_rows,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount,
    SUM(balance_debit_amount) AS balance_debit_amount,
    SUM(open_issue_count) AS open_issue_count,
    SUM(critical_issue_count) AS critical_issue_count
FROM public.vw_sales_money_flow_summary
GROUP BY source_system
ORDER BY source_system;
