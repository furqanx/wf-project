-- Validate scalar product backfill and bundle-component expansion.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_valid_product_items ON COMMIT DROP AS
SELECT components.*
FROM public.vw_sales_order_product_component_analytics components
JOIN public.vw_sales_semantic_order orders
  ON orders.sales_order_id = components.sales_order_id
 AND orders.analytics_channel_type = 'online'
 AND orders.valid_order_count = 1;

ANALYZE tmp_valid_product_items;

SELECT
    source_system,
    product_resolution_method,
    COUNT(*) AS product_component_rows,
    COUNT(DISTINCT sales_order_item_id) AS source_item_rows,
    COUNT(DISTINCT sales_order_id) AS orders,
    COUNT(DISTINCT product_id) AS products,
    SUM(quantity) AS product_units,
    SUM(net_item_amount) AS available_item_net_amount
FROM tmp_valid_product_items
GROUP BY source_system, product_resolution_method
ORDER BY source_system, product_resolution_method;

-- Canonical product-less source items must now be valid configured bundles.
WITH productless AS (
    SELECT items.*
    FROM public.vw_sales_order_item_analytics items
    JOIN public.vw_sales_semantic_order orders
      ON orders.sales_order_id = items.sales_order_id
     AND orders.analytics_channel_type = 'online'
     AND orders.valid_order_count = 1
    WHERE items.product_id IS NULL
),
bundle_shape AS (
    SELECT
        productless.sales_order_item_id,
        COUNT(components.product_bundle_component_id) FILTER (
            WHERE components.is_active
        ) AS active_components
    FROM productless
    LEFT JOIN public.product_bundle_component components
      ON components.bundle_sku_alias_id = productless.product_sku_alias_id
    GROUP BY productless.sales_order_item_id
)
SELECT
    COUNT(*) AS remaining_productless_source_items,
    COUNT(*) FILTER (WHERE active_components > 0) AS configured_bundle_items,
    COUNT(*) FILTER (WHERE active_components = 0) AS unresolved_product_items
FROM bundle_shape;

-- Component expansion must preserve source-item uniqueness for scalar rows and
-- emit exactly the configured number of components for bundle rows.
WITH actual AS (
    SELECT
        sales_order_item_id,
        COUNT(*) AS component_rows,
        COUNT(*) FILTER (WHERE is_bundle_component) AS bundle_component_rows,
        COUNT(*) FILTER (
            WHERE is_bundle_component
              AND item_amount_available_at_product_grain
        ) AS bundle_rows_with_amount_flag,
        COUNT(*) FILTER (
            WHERE is_bundle_component
              AND (
                    gross_item_amount IS NOT NULL
                 OR discount_amount IS NOT NULL
                 OR net_item_amount IS NOT NULL
              )
        ) AS bundle_rows_with_monetary_value
    FROM tmp_valid_product_items
    GROUP BY sales_order_item_id
),
expected AS (
    SELECT
        items.sales_order_item_id,
        CASE
            WHEN items.product_id IS NOT NULL THEN 1
            ELSE COUNT(components.product_bundle_component_id) FILTER (
                WHERE components.is_active
            )
        END AS expected_component_rows
    FROM public.vw_sales_order_item_analytics items
    JOIN public.vw_sales_semantic_order orders
      ON orders.sales_order_id = items.sales_order_id
     AND orders.analytics_channel_type = 'online'
     AND orders.valid_order_count = 1
    LEFT JOIN public.product_bundle_component components
      ON components.bundle_sku_alias_id = items.product_sku_alias_id
    GROUP BY items.sales_order_item_id, items.product_id
)
SELECT
    COUNT(*) FILTER (
        WHERE COALESCE(actual.component_rows, 0) <>
              expected.expected_component_rows
    ) AS component_count_mismatch_items,
    COALESCE(SUM(actual.bundle_rows_with_amount_flag), 0)
        AS bundle_amount_flag_violations,
    COALESCE(SUM(actual.bundle_rows_with_monetary_value), 0)
        AS bundle_monetary_value_violations,
    COUNT(*) FILTER (WHERE actual.sales_order_item_id IS NULL)
        AS source_items_missing_from_component_view
FROM expected
LEFT JOIN actual USING (sales_order_item_id);

ROLLBACK;
