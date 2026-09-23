-- Diagnose product-less items in canonical valid online sales orders.
-- Read-only: candidate mappings are reported but never applied.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_valid_online_orders ON COMMIT DROP AS
SELECT
    sales_order_id,
    source_system,
    marketplace_id,
    store_id,
    external_order_id,
    order_date
FROM public.vw_sales_semantic_order
WHERE analytics_channel_type = 'online'
  AND valid_order_count = 1;

CREATE UNIQUE INDEX ON tmp_valid_online_orders (sales_order_id);
ANALYZE tmp_valid_online_orders;

CREATE TEMP TABLE tmp_productless_items ON COMMIT DROP AS
SELECT
    items.sales_order_item_id,
    items.sales_order_id,
    orders.source_system,
    orders.marketplace_id,
    orders.store_id,
    orders.external_order_id,
    orders.order_date,
    items.source_line_id,
    items.product_sku_alias_id,
    items.source_sku_code,
    items.source_product_name,
    items.source_variation_name,
    items.quantity,
    items.net_item_amount
FROM public.fact_sales_order_item items
JOIN tmp_valid_online_orders orders
  ON orders.sales_order_id = items.sales_order_id
WHERE items.is_active
  AND items.product_id IS NULL;

CREATE INDEX ON tmp_productless_items (source_system, source_sku_code);
CREATE INDEX ON tmp_productless_items (product_sku_alias_id);
ANALYZE tmp_productless_items;

CREATE TEMP TABLE tmp_productless_item_resolution ON COMMIT DROP AS
WITH existing_alias AS (
    SELECT
        missing.sales_order_item_id,
        alias.product_sku_alias_id,
        alias.product_id,
        alias.sku_code,
        alias.sku_name,
        COUNT(components.product_bundle_component_id) FILTER (
            WHERE components.is_active
        ) AS active_bundle_components
    FROM tmp_productless_items missing
    LEFT JOIN public.product_sku_alias alias
      ON alias.product_sku_alias_id = missing.product_sku_alias_id
    LEFT JOIN public.product_bundle_component components
      ON components.bundle_sku_alias_id = alias.product_sku_alias_id
    GROUP BY
        missing.sales_order_item_id,
        alias.product_sku_alias_id,
        alias.product_id,
        alias.sku_code,
        alias.sku_name
),
marketplace_candidates AS (
    SELECT
        missing.sales_order_item_id,
        COUNT(DISTINCT aliases.product_id) FILTER (
            WHERE aliases.product_id IS NOT NULL
        ) AS candidate_products,
        MIN(aliases.product_id) FILTER (
            WHERE aliases.product_id IS NOT NULL
        ) AS candidate_product_id,
        MIN(aliases.product_sku_alias_id) FILTER (
            WHERE aliases.product_id IS NOT NULL
        ) AS candidate_sku_alias_id
    FROM tmp_productless_items missing
    LEFT JOIN public.product_marketplace_alias aliases
      ON aliases.is_active
     AND aliases.marketplace_code IN (
         missing.source_system,
         CASE
             WHEN missing.source_system = 'tiktok_tokopedia' THEN 'tiktok'
             ELSE missing.source_system
         END
     )
     AND LOWER(missing.source_sku_code) IN (
         LOWER(aliases.raw_alias),
         LOWER(aliases.source_sku_code),
         LOWER(aliases.mapped_source_sku_code),
         LOWER(aliases.normalized_alias)
     )
    GROUP BY missing.sales_order_item_id
),
historical_candidates AS (
    SELECT
        missing.sales_order_item_id,
        COUNT(DISTINCT mapped.product_id) AS candidate_products,
        MIN(mapped.product_id) AS candidate_product_id,
        MIN(mapped.product_sku_alias_id) AS candidate_sku_alias_id
    FROM tmp_productless_items missing
    LEFT JOIN public.fact_sales_order_item mapped
      ON mapped.is_active
     AND mapped.product_id IS NOT NULL
     AND LOWER(mapped.source_sku_code) = LOWER(missing.source_sku_code)
     AND LOWER(COALESCE(mapped.source_product_name, '')) =
         LOWER(COALESCE(missing.source_product_name, ''))
     AND LOWER(COALESCE(mapped.source_variation_name, '')) =
         LOWER(COALESCE(missing.source_variation_name, ''))
    LEFT JOIN public.fact_sales_order mapped_order
      ON mapped_order.sales_order_id = mapped.sales_order_id
     AND mapped_order.source_system = missing.source_system
    WHERE mapped_order.sales_order_id IS NOT NULL
       OR mapped.sales_order_item_id IS NULL
    GROUP BY missing.sales_order_item_id
)
SELECT
    missing.*,
    existing_alias.sku_code AS existing_alias_code,
    existing_alias.sku_name AS existing_alias_name,
    existing_alias.active_bundle_components,
    marketplace_candidates.candidate_products AS marketplace_candidate_products,
    marketplace_candidates.candidate_product_id AS marketplace_candidate_product_id,
    marketplace_candidates.candidate_sku_alias_id AS marketplace_candidate_sku_alias_id,
    historical_candidates.candidate_products AS historical_candidate_products,
    historical_candidates.candidate_product_id AS historical_candidate_product_id,
    historical_candidates.candidate_sku_alias_id AS historical_candidate_sku_alias_id,
    CASE
        WHEN existing_alias.product_id IS NOT NULL
            THEN 'existing_alias_product_backfill'
        WHEN existing_alias.active_bundle_components > 0
            THEN 'bundle_requires_component_expansion'
        WHEN marketplace_candidates.candidate_products = 1
            THEN 'unique_marketplace_alias_candidate'
        WHEN historical_candidates.candidate_products = 1
            THEN 'unique_historical_signature_candidate'
        WHEN marketplace_candidates.candidate_products > 1
          OR historical_candidates.candidate_products > 1
            THEN 'ambiguous_candidate'
        ELSE 'unresolved'
    END AS resolution_status,
    CASE
        WHEN existing_alias.product_id IS NOT NULL
            THEN existing_alias.product_id
        WHEN marketplace_candidates.candidate_products = 1
            THEN marketplace_candidates.candidate_product_id
        WHEN historical_candidates.candidate_products = 1
            THEN historical_candidates.candidate_product_id
        ELSE NULL
    END AS proposed_product_id,
    CASE
        WHEN existing_alias.product_id IS NOT NULL
            THEN existing_alias.product_sku_alias_id
        WHEN marketplace_candidates.candidate_products = 1
            THEN marketplace_candidates.candidate_sku_alias_id
        WHEN historical_candidates.candidate_products = 1
            THEN historical_candidates.candidate_sku_alias_id
        ELSE NULL
    END AS proposed_product_sku_alias_id
FROM tmp_productless_items missing
LEFT JOIN existing_alias
  ON existing_alias.sales_order_item_id = missing.sales_order_item_id
LEFT JOIN marketplace_candidates
  ON marketplace_candidates.sales_order_item_id = missing.sales_order_item_id
LEFT JOIN historical_candidates
  ON historical_candidates.sales_order_item_id = missing.sales_order_item_id;

ANALYZE tmp_productless_item_resolution;

-- Summary of the actual cause and safe remediation class.
SELECT
    source_system,
    resolution_status,
    COUNT(*) AS item_rows,
    COUNT(DISTINCT sales_order_id) AS orders,
    COUNT(DISTINCT source_sku_code) AS source_skus,
    SUM(quantity) AS quantity,
    SUM(net_item_amount) AS item_net_amount
FROM tmp_productless_item_resolution
GROUP BY source_system, resolution_status
ORDER BY source_system, resolution_status;

-- Grouped source identities for review.
SELECT
    source_system,
    resolution_status,
    source_sku_code,
    source_product_name,
    source_variation_name,
    existing_alias_code,
    existing_alias_name,
    active_bundle_components,
    proposed_product_id,
    proposed_product_sku_alias_id,
    COUNT(*) AS item_rows,
    COUNT(DISTINCT sales_order_id) AS orders,
    MIN(order_date) AS min_order_date,
    MAX(order_date) AS max_order_date,
    SUM(quantity) AS quantity,
    SUM(net_item_amount) AS item_net_amount
FROM tmp_productless_item_resolution
GROUP BY
    source_system,
    resolution_status,
    source_sku_code,
    source_product_name,
    source_variation_name,
    existing_alias_code,
    existing_alias_name,
    active_bundle_components,
    proposed_product_id,
    proposed_product_sku_alias_id
ORDER BY source_system, item_rows DESC, source_sku_code;

\copy (SELECT * FROM tmp_productless_item_resolution ORDER BY source_system, order_date, sales_order_item_id) TO '/tmp/sales_product_profitability_unmapped_item_detail.csv' CSV HEADER

-- Guardrail: deterministic scalar backfills must never include bundles or
-- ambiguous candidates.
SELECT
    COUNT(*) FILTER (
        WHERE proposed_product_id IS NOT NULL
          AND resolution_status NOT IN (
              'existing_alias_product_backfill',
              'unique_marketplace_alias_candidate',
              'unique_historical_signature_candidate'
          )
    ) AS unsafe_scalar_backfill_candidates,
    COUNT(*) FILTER (
        WHERE resolution_status = 'bundle_requires_component_expansion'
          AND active_bundle_components = 0
    ) AS bundle_without_component_rows
FROM tmp_productless_item_resolution;

ROLLBACK;
