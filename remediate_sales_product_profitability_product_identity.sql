-- Backfill scalar product identities and expose bundle components safely.
-- Bundle item amounts remain NULL at component grain until an allocation
-- method is governed; this prevents monetary double counting.

BEGIN;

UPDATE public.fact_sales_order_item items
SET
    product_id = aliases.product_id,
    notes = CONCAT_WS(
        ' | ',
        items.notes,
        'Product identity backfilled from existing product_sku_alias'
    ),
    updated_at = NOW()
FROM public.product_sku_alias aliases
WHERE aliases.product_sku_alias_id = items.product_sku_alias_id
  AND aliases.is_active
  AND aliases.product_id IS NOT NULL
  AND items.product_id IS NULL;

CREATE OR REPLACE VIEW public.vw_sales_order_product_component_analytics AS
SELECT
    items.sales_order_item_id,
    items.sales_order_id,
    items.source_system,
    items.analytics_channel_type,
    items.marketplace_id,
    items.store_id,
    items.b2b_partner_id,
    items.customer_id,
    items.external_order_id,
    items.order_date,
    items.order_datetime,
    items.order_status,
    items.source_line_id,
    items.product_sku_alias_id,
    items.product_id,
    items.source_sku_code,
    items.source_product_name,
    items.source_variation_name,
    items.quantity,
    items.quantity_returned,
    items.unit,
    items.unit_price,
    items.gross_item_amount,
    items.discount_amount,
    items.net_item_amount,
    FALSE AS is_bundle_component,
    1::numeric AS component_quantity_per_bundle,
    'direct_product'::text AS product_resolution_method,
    TRUE AS item_amount_available_at_product_grain
FROM public.vw_sales_order_item_analytics items
WHERE items.product_id IS NOT NULL

UNION ALL

SELECT
    items.sales_order_item_id,
    items.sales_order_id,
    items.source_system,
    items.analytics_channel_type,
    items.marketplace_id,
    items.store_id,
    items.b2b_partner_id,
    items.customer_id,
    items.external_order_id,
    items.order_date,
    items.order_datetime,
    items.order_status,
    items.source_line_id,
    items.product_sku_alias_id,
    components.component_product_id AS product_id,
    components.component_sku_code AS source_sku_code,
    products.product_name AS source_product_name,
    items.source_variation_name,
    items.quantity * components.component_qty AS quantity,
    items.quantity_returned * components.component_qty AS quantity_returned,
    components.component_unit AS unit,
    NULL::numeric AS unit_price,
    NULL::numeric AS gross_item_amount,
    NULL::numeric AS discount_amount,
    NULL::numeric AS net_item_amount,
    TRUE AS is_bundle_component,
    components.component_qty AS component_quantity_per_bundle,
    'bundle_component_expansion'::text AS product_resolution_method,
    FALSE AS item_amount_available_at_product_grain
FROM public.vw_sales_order_item_analytics items
JOIN public.product_bundle_component components
  ON components.bundle_sku_alias_id = items.product_sku_alias_id
 AND components.is_active
JOIN public.dim_product products
  ON products.product_id = components.component_product_id
 AND products.is_active
WHERE items.product_id IS NULL;

COMMENT ON VIEW public.vw_sales_order_product_component_analytics IS
'Canonical product-component grain. Scalar items retain item amounts; bundles expand to component quantities and deliberately expose NULL monetary values until an allocation policy is governed.';

COMMIT;
