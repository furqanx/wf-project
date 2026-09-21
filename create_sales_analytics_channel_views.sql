-- Canonical sales channel views for analytics and dashboards.
--
-- Decisions encoded here:
-- - Marketplace sales come only from their direct source systems.
-- - Accurate records that represent marketplace sales remain in the fact table
--   for traceability, but are excluded from analytics.
-- - Positive Accurate offline invoices are split into B2B and retail using the
--   Accurate customer-number prefix.
-- - Exact marketplace duplicates are counted once. A reused external order ID
--   with a different amount or product basket remains a separate transaction.
--
-- Safe to rerun. The base fact tables are not modified.

BEGIN;

DROP VIEW IF EXISTS public.vw_sales_order_item_analytics;
DROP VIEW IF EXISTS public.vw_sales_order_analytics;
DROP VIEW IF EXISTS public.vw_sales_order_channel_classification;

CREATE OR REPLACE VIEW public.vw_sales_order_channel_classification AS
WITH item_product_totals AS (
    SELECT
        sales_order_id,
        product_id,
        SUM(quantity) AS quantity
    FROM public.fact_sales_order_item
    WHERE is_active = TRUE
    GROUP BY sales_order_id, product_id
),
item_signatures AS (
    SELECT
        sales_order_id,
        STRING_AGG(
            CONCAT(COALESCE(product_id::text, 'null'), ':', quantity::text),
            ',' ORDER BY product_id NULLS LAST
        ) AS product_quantity_signature
    FROM item_product_totals
    GROUP BY sales_order_id
),
parsed AS (
    SELECT
        fso.*,
        NULLIF(BTRIM(SUBSTRING(fso.notes FROM 'customer_name=([^|]+)')), '') AS source_customer_name,
        NULLIF(BTRIM(SUBSTRING(fso.notes FROM 'customer_no=([^|]+)')), '') AS accurate_customer_no,
        COALESCE(sig.product_quantity_signature, '') AS product_quantity_signature,
        EXISTS (
            SELECT 1
            FROM public.fact_sales_order marketplace_order
            WHERE marketplace_order.is_active = TRUE
              AND marketplace_order.source_system IN ('shopee', 'lazada', 'tiktok_tokopedia')
              AND marketplace_order.external_order_id = fso.external_order_id
        ) AS has_direct_marketplace_order
    FROM public.fact_sales_order fso
    LEFT JOIN item_signatures sig
        ON sig.sales_order_id = fso.sales_order_id
    WHERE fso.is_active = TRUE
      AND fso.source_system IN ('accurate', 'shopee', 'lazada', 'tiktok_tokopedia')
),
classified AS (
    SELECT
        parsed.*,
        CASE
            WHEN source_system IN ('shopee', 'lazada', 'tiktok_tokopedia') THEN 'online'
            WHEN source_system = 'accurate'
             AND NOT has_direct_marketplace_order
             AND COALESCE(source_customer_name, '') NOT ILIKE 'Shopee %'
             AND external_order_id !~ '^[0-9]{6}[A-Z0-9]+$'
             AND external_order_id !~ '^[0-9]{17,20}$'
             AND (
                    external_order_id ILIKE 'INV%'
                 OR external_order_id ILIKE 'SI.%'
                 OR external_order_id ILIKE 'LAP.%'
                 OR external_order_id ILIKE 'DO%'
             )
             AND accurate_customer_no ~ '^(D|A|K)\.' THEN 'offline_b2b'
            WHEN source_system = 'accurate'
             AND NOT has_direct_marketplace_order
             AND COALESCE(source_customer_name, '') NOT ILIKE 'Shopee %'
             AND external_order_id !~ '^[0-9]{6}[A-Z0-9]+$'
             AND external_order_id !~ '^[0-9]{17,20}$'
             AND (
                    external_order_id ILIKE 'INV%'
                 OR external_order_id ILIKE 'SI.%'
                 OR external_order_id ILIKE 'LAP.%'
                 OR external_order_id ILIKE 'DO%'
             )
             AND accurate_customer_no ~ '^C\.' THEN 'offline_retail'
            ELSE NULL
        END AS analytics_channel_type,
        CASE LOWER(COALESCE(order_status, ''))
            WHEN 'delivered' THEN 10
            WHEN 'completed' THEN 10
            WHEN 'complete' THEN 10
            WHEN 'selesai' THEN 10
            WHEN 'ready_to_ship' THEN 20
            WHEN 'packed' THEN 20
            WHEN 'shipped' THEN 20
            WHEN 'confirmed' THEN 30
            WHEN 'approved' THEN 30
            WHEN 'pending' THEN 40
            WHEN 'canceled' THEN 50
            WHEN 'cancelled' THEN 50
            WHEN 'dibatalkan' THEN 50
            ELSE 45
        END AS analytics_status_rank
    FROM parsed
),
ranked AS (
    SELECT
        classified.*,
        CASE
            WHEN source_system IN ('shopee', 'lazada', 'tiktok_tokopedia') THEN
                ROW_NUMBER() OVER (
                    PARTITION BY
                        source_system,
                        external_order_id,
                        COALESCE(net_order_amount, 0),
                        product_quantity_signature
                    ORDER BY analytics_status_rank, sales_order_id
                )
            ELSE 1
        END AS analytics_duplicate_rank
    FROM classified
)
SELECT
    ranked.*,
    (
        analytics_channel_type IS NOT NULL
        AND analytics_duplicate_rank = 1
    ) AS is_analytics_included,
    CASE
        WHEN analytics_channel_type IS NOT NULL
         AND analytics_duplicate_rank = 1 THEN NULL
        WHEN source_system = 'accurate'
         AND has_direct_marketplace_order THEN 'accurate_marketplace_duplicate'
        WHEN source_system = 'accurate'
         AND (
                source_customer_name ILIKE 'Shopee %'
             OR external_order_id ~ '^[0-9]{6}[A-Z0-9]+$'
             OR external_order_id ~ '^[0-9]{17,20}$'
         ) THEN 'accurate_online_without_direct_source'
        WHEN source_system = 'accurate'
         AND analytics_channel_type IS NULL THEN 'accurate_offline_unclassified'
        WHEN analytics_duplicate_rank > 1 THEN 'duplicate_marketplace_record'
        ELSE 'not_in_analytics_scope'
    END AS analytics_exclusion_reason
FROM ranked;

COMMENT ON VIEW public.vw_sales_order_channel_classification IS
'Auditable sales-channel classification and marketplace deduplication. Use is_analytics_included to select canonical analytical orders.';

CREATE OR REPLACE VIEW public.vw_sales_order_analytics AS
SELECT *
FROM public.vw_sales_order_channel_classification
WHERE is_analytics_included = TRUE;

COMMENT ON VIEW public.vw_sales_order_analytics IS
'Canonical order-grain sales dataset. Accurate contributes only positively classified offline B2B/retail sales; online sales come from direct marketplace sources.';

CREATE OR REPLACE VIEW public.vw_sales_order_item_analytics AS
SELECT
    fsoi.*,
    fso.source_system,
    fso.analytics_channel_type,
    fso.marketplace_id,
    fso.store_id,
    fso.b2b_partner_id,
    fso.customer_id,
    fso.external_order_id,
    fso.order_date,
    fso.order_datetime,
    fso.order_status
FROM public.fact_sales_order_item fsoi
JOIN public.vw_sales_order_analytics fso
    ON fso.sales_order_id = fsoi.sales_order_id
WHERE fsoi.is_active = TRUE;

COMMENT ON VIEW public.vw_sales_order_item_analytics IS
'Canonical item-grain sales dataset restricted to orders included by vw_sales_order_analytics.';

COMMIT;
