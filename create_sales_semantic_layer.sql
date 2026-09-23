-- Official sales semantic layer for Superset and other reporting consumers.
--
-- Metric policy:
-- - A canceled order remains auditable but contributes zero recognized revenue,
--   valid orders, and recognized units.
-- - Recognized revenue uses canonical order-header net_order_amount.
-- - Completed refunds reduce recognized revenue after returns.
-- - Product monetary values remain item values and are not official revenue.
-- - Fulfillment rates apply only to non-canceled online orders.
-- - Sales target metrics are intentionally absent until a sales target source
--   and grain are approved.

BEGIN;

CREATE OR REPLACE VIEW public.vw_sales_semantic_order AS
WITH order_resolution AS (
    SELECT
        candidate.sales_order_id AS source_sales_order_id,
        canonical.sales_order_id AS canonical_sales_order_id
    FROM public.vw_sales_order_channel_classification candidate
    JOIN public.vw_sales_order_channel_classification canonical
        ON canonical.source_system = candidate.source_system
       AND canonical.external_order_id = candidate.external_order_id
       AND COALESCE(canonical.net_order_amount, 0) = COALESCE(candidate.net_order_amount, 0)
       AND canonical.product_quantity_signature = candidate.product_quantity_signature
       AND canonical.is_analytics_included = TRUE
    WHERE candidate.source_system IN ('shopee', 'lazada', 'tiktok_tokopedia')
),
return_header AS (
    SELECT
        resolution.canonical_sales_order_id AS sales_order_id,
        COUNT(*) AS recorded_return_count,
        COUNT(*) FILTER (
            WHERE fsr.return_type <> 'cancellation'
              AND LOWER(COALESCE(fsr.return_status, '')) NOT LIKE '%dibatalkan%'
              AND LOWER(COALESCE(fsr.return_status, '')) NOT LIKE '%diproses%'
              AND LOWER(COALESCE(fsr.return_status, '')) NOT LIKE 'in transit:%'
              AND (
                    fsr.return_completed_at IS NOT NULL
                 OR LOWER(COALESCE(fsr.return_status, '')) = 'selesai'
              )
        ) AS completed_return_count,
        SUM(COALESCE(fsr.refund_amount, 0)) AS recorded_refund_amount,
        SUM(COALESCE(fsr.refund_amount, 0)) FILTER (
            WHERE fsr.return_type <> 'cancellation'
              AND LOWER(COALESCE(fsr.return_status, '')) NOT LIKE '%dibatalkan%'
              AND LOWER(COALESCE(fsr.return_status, '')) NOT LIKE '%diproses%'
              AND LOWER(COALESCE(fsr.return_status, '')) NOT LIKE 'in transit:%'
              AND (
                    fsr.return_completed_at IS NOT NULL
                 OR LOWER(COALESCE(fsr.return_status, '')) = 'selesai'
              )
        ) AS completed_refund_amount,
        SUM(COALESCE(fsr.return_shipping_amount, 0)) AS return_shipping_amount,
        MIN(fsr.return_requested_at) AS first_return_requested_at,
        MAX(fsr.return_completed_at) AS last_return_completed_at
    FROM public.fact_sales_return fsr
    JOIN order_resolution resolution
        ON resolution.source_sales_order_id = fsr.sales_order_id
    WHERE fsr.is_active = TRUE
      AND fsr.sales_order_id IS NOT NULL
    GROUP BY resolution.canonical_sales_order_id
),
return_items AS (
    SELECT
        resolution.canonical_sales_order_id AS sales_order_id,
        SUM(COALESCE(fsri.return_qty, 0)) AS returned_units,
        SUM(COALESCE(fsri.refund_item_amount, 0)) AS return_item_refund_amount
    FROM public.fact_sales_return fsr
    JOIN public.fact_sales_return_item fsri
        ON fsri.sales_return_id = fsr.sales_return_id
       AND fsri.is_active = TRUE
    JOIN order_resolution resolution
        ON resolution.source_sales_order_id = fsr.sales_order_id
    WHERE fsr.is_active = TRUE
      AND fsr.sales_order_id IS NOT NULL
    GROUP BY resolution.canonical_sales_order_id
),
recognized_refund AS (
    SELECT
        sales_order_id,
        SUM(recognized_refund_amount) FILTER (
            WHERE refund_value_status = 'recognized'
        ) AS recognized_refund_amount
    FROM public.vw_sales_refund_semantic
    GROUP BY sales_order_id
),
fulfillment AS (
    SELECT
        resolution.canonical_sales_order_id AS sales_order_id,
        COUNT(*) AS fulfillment_count,
        BOOL_OR(fsf.tracking_number IS NOT NULL) AS has_tracking,
        BOOL_OR(fsf.shipped_at IS NOT NULL) AS has_shipped,
        BOOL_OR(fsf.delivered_at IS NOT NULL) AS has_delivered,
        MIN(fsf.ready_to_ship_at) AS first_ready_to_ship_at,
        MIN(fsf.shipped_at) AS first_shipped_at,
        MAX(fsf.delivered_at) AS last_delivered_at
    FROM public.fact_sales_fulfillment fsf
    JOIN order_resolution resolution
        ON resolution.source_sales_order_id = fsf.sales_order_id
    WHERE fsf.is_active = TRUE
      AND fsf.sales_order_id IS NOT NULL
    GROUP BY resolution.canonical_sales_order_id
)
SELECT
    orders.*,
    1::bigint AS canonical_order_count,
    CASE WHEN orders.is_canceled THEN 0 ELSE 1 END::bigint AS valid_order_count,
    CASE WHEN orders.is_canceled THEN 1 ELSE 0 END::bigint AS canceled_order_count,
    orders.order_revenue AS booked_revenue,
    CASE
        WHEN orders.is_canceled THEN 0::numeric
        ELSE orders.order_revenue
    END AS recognized_revenue,
    CASE
        WHEN orders.is_canceled THEN 0::numeric
        ELSE orders.units_sold
    END AS recognized_units_sold,
    COALESCE(rh.recorded_return_count, 0)::bigint AS recorded_return_count,
    COALESCE(rh.completed_return_count, 0)::bigint AS completed_return_count,
    CASE
        WHEN COALESCE(rh.recorded_return_count, 0) > 0 THEN 1
        ELSE 0
    END::bigint AS returned_order_count,
    CASE
        WHEN COALESCE(rh.completed_return_count, 0) > 0 THEN 1
        ELSE 0
    END::bigint AS completed_return_order_count,
    COALESCE(rh.recorded_refund_amount, 0) AS recorded_refund_amount,
    CASE
        WHEN orders.is_canceled THEN 0::numeric
        ELSE COALESCE(rr.recognized_refund_amount, 0)
    END AS recognized_refund_amount,
    COALESCE(rh.return_shipping_amount, 0) AS return_shipping_amount,
    COALESCE(ri.returned_units, 0) AS returned_units,
    COALESCE(ri.return_item_refund_amount, 0) AS return_item_refund_amount,
    CASE
        WHEN orders.is_canceled THEN 0::numeric
        ELSE orders.order_revenue
            - COALESCE(rr.recognized_refund_amount, 0)
    END AS net_revenue_after_returns,
    rh.first_return_requested_at,
    rh.last_return_completed_at,
    CASE
        WHEN orders.analytics_channel_type = 'online' AND NOT orders.is_canceled THEN 1
        ELSE 0
    END::bigint AS fulfillment_eligible_order_count,
    CASE
        WHEN orders.analytics_channel_type = 'online'
         AND NOT orders.is_canceled
         AND COALESCE(f.fulfillment_count, 0) > 0 THEN 1
        ELSE 0
    END::bigint AS fulfillment_matched_order_count,
    CASE
        WHEN orders.analytics_channel_type = 'online'
         AND NOT orders.is_canceled
         AND COALESCE(f.has_shipped, FALSE) THEN 1
        ELSE 0
    END::bigint AS shipped_order_count,
    CASE
        WHEN orders.analytics_channel_type = 'online'
         AND NOT orders.is_canceled
         AND COALESCE(f.has_delivered, FALSE) THEN 1
        ELSE 0
    END::bigint AS delivered_order_count,
    COALESCE(f.fulfillment_count, 0)::bigint AS fulfillment_count,
    COALESCE(f.has_tracking, FALSE) AS has_tracking,
    COALESCE(f.has_shipped, FALSE) AS has_shipped,
    COALESCE(f.has_delivered, FALSE) AS has_delivered,
    f.first_ready_to_ship_at,
    f.first_shipped_at,
    f.last_delivered_at
FROM public.vw_sales_order_summary orders
LEFT JOIN return_header rh
    ON rh.sales_order_id = orders.sales_order_id
LEFT JOIN return_items ri
    ON ri.sales_order_id = orders.sales_order_id
LEFT JOIN recognized_refund rr
    ON rr.sales_order_id = orders.sales_order_id
LEFT JOIN fulfillment f
    ON f.sales_order_id = orders.sales_order_id;

COMMENT ON VIEW public.vw_sales_semantic_order IS
'Official order-grain sales semantic layer with recognized revenue, returns, and fulfillment flags.';

CREATE OR REPLACE VIEW public.vw_sales_semantic_daily AS
SELECT
    order_date,
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name,
    SUM(canonical_order_count) AS canonical_order_count,
    SUM(valid_order_count) AS valid_order_count,
    SUM(canceled_order_count) AS canceled_order_count,
    SUM(booked_revenue) AS booked_revenue,
    SUM(recognized_revenue) AS recognized_revenue,
    SUM(recognized_units_sold) AS recognized_units_sold,
    SUM(recorded_return_count) AS recorded_return_count,
    SUM(completed_return_count) AS completed_return_count,
    SUM(returned_order_count) AS returned_order_count,
    SUM(completed_return_order_count) AS completed_return_order_count,
    SUM(recorded_refund_amount) AS recorded_refund_amount,
    SUM(recognized_refund_amount) AS recognized_refund_amount,
    SUM(returned_units) AS returned_units,
    SUM(net_revenue_after_returns) AS net_revenue_after_returns,
    SUM(fulfillment_eligible_order_count) AS fulfillment_eligible_order_count,
    SUM(fulfillment_matched_order_count) AS fulfillment_matched_order_count,
    SUM(shipped_order_count) AS shipped_order_count,
    SUM(delivered_order_count) AS delivered_order_count,
    SUM(recognized_revenue) / NULLIF(SUM(valid_order_count), 0) AS average_order_value,
    SUM(completed_return_order_count)::numeric
        / NULLIF(SUM(valid_order_count), 0) AS completed_return_rate,
    SUM(fulfillment_matched_order_count)::numeric
        / NULLIF(SUM(fulfillment_eligible_order_count), 0) AS fulfillment_coverage_rate,
    SUM(delivered_order_count)::numeric
        / NULLIF(SUM(fulfillment_eligible_order_count), 0) AS delivery_rate
FROM public.vw_sales_semantic_order
GROUP BY
    order_date,
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name;

COMMENT ON VIEW public.vw_sales_semantic_daily IS
'Daily official sales metrics at channel/source/store grain.';

CREATE OR REPLACE VIEW public.vw_sales_semantic_monthly AS
SELECT
    DATE_TRUNC('month', order_date)::date AS order_month,
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name,
    SUM(canonical_order_count) AS canonical_order_count,
    SUM(valid_order_count) AS valid_order_count,
    SUM(canceled_order_count) AS canceled_order_count,
    SUM(booked_revenue) AS booked_revenue,
    SUM(recognized_revenue) AS recognized_revenue,
    SUM(recognized_units_sold) AS recognized_units_sold,
    SUM(recorded_return_count) AS recorded_return_count,
    SUM(completed_return_count) AS completed_return_count,
    SUM(returned_order_count) AS returned_order_count,
    SUM(completed_return_order_count) AS completed_return_order_count,
    SUM(recorded_refund_amount) AS recorded_refund_amount,
    SUM(recognized_refund_amount) AS recognized_refund_amount,
    SUM(returned_units) AS returned_units,
    SUM(net_revenue_after_returns) AS net_revenue_after_returns,
    SUM(fulfillment_eligible_order_count) AS fulfillment_eligible_order_count,
    SUM(fulfillment_matched_order_count) AS fulfillment_matched_order_count,
    SUM(shipped_order_count) AS shipped_order_count,
    SUM(delivered_order_count) AS delivered_order_count,
    SUM(recognized_revenue) / NULLIF(SUM(valid_order_count), 0) AS average_order_value,
    SUM(completed_return_order_count)::numeric
        / NULLIF(SUM(valid_order_count), 0) AS completed_return_rate,
    SUM(fulfillment_matched_order_count)::numeric
        / NULLIF(SUM(fulfillment_eligible_order_count), 0) AS fulfillment_coverage_rate,
    SUM(delivered_order_count)::numeric
        / NULLIF(SUM(fulfillment_eligible_order_count), 0) AS delivery_rate
FROM public.vw_sales_semantic_order
GROUP BY
    DATE_TRUNC('month', order_date)::date,
    analytics_channel_type,
    source_system,
    marketplace_id,
    marketplace_name,
    store_id,
    store_name;

COMMENT ON VIEW public.vw_sales_semantic_monthly IS
'Monthly official sales metrics calculated from order-grain semantic facts.';

CREATE OR REPLACE VIEW public.vw_sales_semantic_product_daily AS
SELECT
    items.order_date,
    items.analytics_channel_type,
    items.source_system,
    items.marketplace_id,
    dm.marketplace_name,
    items.store_id,
    ds.store_name,
    items.product_id,
    dp.product_name,
    dp.product_category,
    dp.product_type,
    dp.base_unit,
    dp.net_weight_value,
    dp.net_weight_unit,
    COUNT(DISTINCT items.sales_order_id) AS valid_order_count,
    COUNT(*) AS item_row_count,
    SUM(items.quantity) AS units_sold,
    SUM(items.quantity_returned) AS units_returned_recorded,
    SUM(items.gross_item_amount) AS item_gross_amount,
    SUM(items.discount_amount) AS item_discount_amount,
    SUM(items.net_item_amount) AS item_net_amount
FROM public.vw_sales_order_product_component_analytics items
JOIN public.vw_sales_semantic_order orders
    ON orders.sales_order_id = items.sales_order_id
   AND orders.valid_order_count = 1
LEFT JOIN public.dim_product dp
    ON dp.product_id = items.product_id
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = items.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = items.store_id
GROUP BY
    items.order_date,
    items.analytics_channel_type,
    items.source_system,
    items.marketplace_id,
    dm.marketplace_name,
    items.store_id,
    ds.store_name,
    items.product_id,
    dp.product_name,
    dp.product_category,
    dp.product_type,
    dp.base_unit,
    dp.net_weight_value,
    dp.net_weight_unit;

COMMENT ON VIEW public.vw_sales_semantic_product_daily IS
'Daily valid-order product metrics. Item monetary values are diagnostic and are not official revenue.';

COMMIT;
