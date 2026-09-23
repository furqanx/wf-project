-- Read-only readiness audit for product-level sales profitability.
-- This audit does not allocate order-level costs to products.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_product_profitability_orders ON COMMIT DROP AS
SELECT
    sales_order_id,
    source_system,
    store_id,
    external_order_id,
    order_date,
    recognized_revenue
FROM public.vw_sales_semantic_order
WHERE analytics_channel_type = 'online'
  AND valid_order_count = 1;

CREATE UNIQUE INDEX ON tmp_product_profitability_orders (sales_order_id);
CREATE INDEX ON tmp_product_profitability_orders (source_system, external_order_id);
ANALYZE tmp_product_profitability_orders;

CREATE TEMP TABLE tmp_product_profitability_items ON COMMIT DROP AS
SELECT
    items.sales_order_item_id,
    items.sales_order_id,
    orders.source_system,
    orders.store_id,
    orders.external_order_id,
    orders.order_date,
    items.source_line_id,
    items.source_sku_code,
    items.product_id,
    items.quantity,
    items.net_item_amount,
    items.is_bundle_component,
    items.product_resolution_method,
    items.item_amount_available_at_product_grain
FROM public.vw_sales_order_product_component_analytics items
JOIN tmp_product_profitability_orders orders
  ON orders.sales_order_id = items.sales_order_id;

CREATE INDEX ON tmp_product_profitability_items (sales_order_id);
CREATE INDEX ON tmp_product_profitability_items (sales_order_id, source_line_id);
CREATE INDEX ON tmp_product_profitability_items (sales_order_id, source_sku_code);
ANALYZE tmp_product_profitability_items;

CREATE TEMP TABLE tmp_selected_product_fees ON COMMIT DROP AS
SELECT
    sales_settlement_fee_detail_id,
    source_system,
    store_id,
    sales_order_id,
    external_order_id,
    NULLIF(BTRIM(external_order_item_id), '') AS external_order_item_id,
    NULLIF(BTRIM(source_sku_code), '') AS source_sku_code,
    fee_grain_type,
    marketplace_cost_amount
FROM public.vw_sales_marketplace_fee_semantic
WHERE is_marketplace_cost_selected
  AND marketplace_cost_amount IS NOT NULL;

CREATE UNIQUE INDEX ON tmp_selected_product_fees (
    sales_settlement_fee_detail_id
);
CREATE INDEX ON tmp_selected_product_fees (sales_order_id);
ANALYZE tmp_selected_product_fees;

-- 1. Product-sales foundation. All active valid-order items should have a
-- product identity before any product-level metric is published.
SELECT
    source_system,
    COUNT(DISTINCT sales_order_id) AS valid_orders_with_items,
    COUNT(*) AS item_rows,
    COUNT(*) FILTER (WHERE product_id IS NULL) AS items_without_product,
    COUNT(DISTINCT sales_order_item_id) FILTER (
        WHERE is_bundle_component
    ) AS bundle_source_items,
    COUNT(DISTINCT product_id) AS products,
    SUM(quantity) AS units_sold,
    SUM(net_item_amount) AS diagnostic_item_net_amount
FROM tmp_product_profitability_items
GROUP BY source_system
ORDER BY source_system;

-- 2. Determine whether each selected marketplace-cost row identifies exactly
-- one product. Source item identity has priority over the SKU fallback.
CREATE TEMP TABLE tmp_product_fee_resolution ON COMMIT DROP AS
WITH item_identity AS (
    SELECT
        fees.sales_settlement_fee_detail_id,
        COUNT(items.sales_order_item_id) AS matched_item_rows,
        COUNT(DISTINCT items.product_id) AS matched_products,
        MIN(items.product_id) AS product_id
    FROM tmp_selected_product_fees fees
    LEFT JOIN tmp_product_profitability_items items
      ON items.sales_order_id = fees.sales_order_id
     AND items.source_line_id = fees.external_order_item_id
    WHERE fees.external_order_item_id IS NOT NULL
    GROUP BY fees.sales_settlement_fee_detail_id
),
sku_identity AS (
    SELECT
        fees.sales_settlement_fee_detail_id,
        COUNT(items.sales_order_item_id) AS matched_item_rows,
        COUNT(DISTINCT items.product_id) AS matched_products,
        MIN(items.product_id) AS product_id
    FROM tmp_selected_product_fees fees
    LEFT JOIN tmp_product_profitability_items items
      ON items.sales_order_id = fees.sales_order_id
     AND items.source_sku_code = fees.source_sku_code
    WHERE fees.source_sku_code IS NOT NULL
    GROUP BY fees.sales_settlement_fee_detail_id
),
order_shape AS (
    SELECT
        sales_order_id,
        COUNT(*) AS item_rows,
        COUNT(DISTINCT product_id) AS products,
        MIN(product_id) AS product_id
    FROM tmp_product_profitability_items
    GROUP BY sales_order_id
)
SELECT
    fees.*,
    CASE
        WHEN fees.sales_order_id IS NULL THEN 'unlinked_order'
        WHEN identity_match.matched_products = 1
            THEN 'direct_external_item_identity'
        WHEN sku_match.matched_products = 1
            THEN 'direct_order_sku_identity'
        WHEN order_shape.products = 1
            THEN 'single_product_order_inference'
        WHEN order_shape.products > 1
            THEN 'multi_product_order_requires_allocation'
        ELSE 'order_without_resolvable_product'
    END AS product_attribution_status,
    CASE
        WHEN identity_match.matched_products = 1 THEN identity_match.product_id
        WHEN sku_match.matched_products = 1 THEN sku_match.product_id
        WHEN order_shape.products = 1 THEN order_shape.product_id
        ELSE NULL
    END AS resolved_product_id,
    COALESCE(identity_match.matched_item_rows, 0) AS item_identity_match_rows,
    COALESCE(sku_match.matched_item_rows, 0) AS sku_match_rows,
    COALESCE(order_shape.item_rows, 0) AS order_item_rows,
    COALESCE(order_shape.products, 0) AS order_products
FROM tmp_selected_product_fees fees
LEFT JOIN item_identity identity_match
  ON identity_match.sales_settlement_fee_detail_id =
     fees.sales_settlement_fee_detail_id
LEFT JOIN sku_identity sku_match
  ON sku_match.sales_settlement_fee_detail_id =
     fees.sales_settlement_fee_detail_id
LEFT JOIN order_shape
  ON order_shape.sales_order_id = fees.sales_order_id;

CREATE INDEX ON tmp_product_fee_resolution (
    source_system,
    product_attribution_status
);
ANALYZE tmp_product_fee_resolution;

SELECT
    source_system,
    product_attribution_status,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT sales_order_id) AS orders,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_product_fee_resolution
GROUP BY source_system, product_attribution_status
ORDER BY source_system, product_attribution_status;

-- 3. Direct attribution is publishable without allocation. Single-product
-- inference is shown separately and requires an explicit governance decision.
SELECT
    source_system,
    COUNT(*) AS selected_fee_rows,
    COUNT(*) FILTER (
        WHERE product_attribution_status IN (
            'direct_external_item_identity',
            'direct_order_sku_identity'
        )
    ) AS directly_attributable_fee_rows,
    COUNT(*) FILTER (
        WHERE product_attribution_status = 'single_product_order_inference'
    ) AS single_product_inference_rows,
    COUNT(*) FILTER (
        WHERE product_attribution_status =
              'multi_product_order_requires_allocation'
    ) AS allocation_required_fee_rows,
    SUM(marketplace_cost_amount) AS selected_marketplace_cost,
    SUM(marketplace_cost_amount) FILTER (
        WHERE product_attribution_status IN (
            'direct_external_item_identity',
            'direct_order_sku_identity'
        )
    ) AS directly_attributable_marketplace_cost,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE product_attribution_status IN (
                'direct_external_item_identity',
                'direct_order_sku_identity'
            )
        ) / NULLIF(COUNT(*), 0),
        2
    ) AS direct_fee_row_coverage_pct,
    ROUND(
        100.0 * SUM(ABS(marketplace_cost_amount)) FILTER (
            WHERE product_attribution_status IN (
                'direct_external_item_identity',
                'direct_order_sku_identity'
            )
        ) / NULLIF(SUM(ABS(marketplace_cost_amount)), 0),
        2
    ) AS direct_fee_amount_coverage_pct
FROM tmp_product_fee_resolution
GROUP BY source_system
ORDER BY source_system;

-- 4. Readiness matrix. Revenue at product grain remains diagnostic because
-- official revenue is order-grain; COGS and credible cost are unavailable.
SELECT *
FROM (VALUES
    ('product_identity', 'ready',
     'Measured from active items belonging to canonical valid orders.'),
    ('units_sold', 'ready',
     'Available at governed product grain.'),
    ('product_item_revenue', 'diagnostic',
     'Item net amount is not official canonical revenue.'),
    ('marketplace_cost', 'coverage_dependent',
     'Only directly attributed rows are safe without an allocation policy.'),
    ('refund_value', 'not_product_attributed',
     'Governed refund values currently resolve at order grain.'),
    ('ads_penalty_adjustment', 'not_product_attributed',
     'Most governed values use order or store-period grain.'),
    ('cogs', 'unavailable',
     'No authoritative effective-dated COGS source is loaded.'),
    ('credible_cost', 'unavailable',
     'No authoritative allocation source is loaded.'),
    ('product_profit', 'not_ready',
     'Cannot be published before COGS and allocation governance exist.')
) AS readiness(component, status, rationale);

-- 5. Integrity guardrails. Every value should be zero.
SELECT
    COUNT(*) FILTER (
        WHERE product_attribution_status IN (
            'direct_external_item_identity',
            'direct_order_sku_identity',
            'single_product_order_inference'
        )
          AND resolved_product_id IS NULL
    ) AS attributed_without_product_rows,
    COUNT(*) FILTER (
        WHERE product_attribution_status =
              'multi_product_order_requires_allocation'
          AND resolved_product_id IS NOT NULL
    ) AS allocated_without_policy_rows,
    COUNT(*) FILTER (
        WHERE marketplace_cost_amount IS NULL
    ) AS selected_without_cost_amount_rows
FROM tmp_product_fee_resolution;

ROLLBACK;
