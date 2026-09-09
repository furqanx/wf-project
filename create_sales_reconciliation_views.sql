-- Sales reconciliation helper views.
-- Scope:
-- - Read-only views over Phase 1-5 facts and public.data_quality_issue
-- - Designed for dashboard/query consumption, not as new storage tables
--
-- Safe to rerun.

BEGIN;

DROP VIEW IF EXISTS public.vw_sales_money_flow_summary;
DROP VIEW IF EXISTS public.vw_sales_balance_reconciliation;
DROP VIEW IF EXISTS public.vw_sales_settlement_reconciliation;
DROP VIEW IF EXISTS public.vw_sales_fulfillment_reconciliation;
DROP VIEW IF EXISTS public.vw_sales_return_reconciliation;
DROP VIEW IF EXISTS public.vw_sales_order_reconciliation;

CREATE OR REPLACE VIEW public.vw_sales_order_reconciliation AS
WITH issue_flags AS (
    SELECT
        sales_order_id,
        BOOL_OR(issue_type = 'phase1_order_without_settlement' AND issue_status = 'open') AS has_open_order_without_settlement_issue,
        BOOL_OR(issue_type = 'phase1_order_without_fulfillment' AND issue_status = 'open') AS has_open_order_without_fulfillment_issue,
        COUNT(*) FILTER (WHERE issue_status = 'open') AS open_issue_count,
        COUNT(*) FILTER (WHERE issue_status = 'open' AND issue_severity = 'warning') AS warning_issue_count
    FROM public.data_quality_issue
    WHERE issue_domain = 'sales_money_flow'
      AND source_table = 'fact_sales_order'
    GROUP BY sales_order_id
),
settlement_summary AS (
    SELECT
        sales_order_id,
        COUNT(*) AS settlement_rows,
        SUM(settlement_amount) AS settlement_amount,
        MIN(settled_at) AS first_settled_at,
        MAX(settled_at) AS last_settled_at
    FROM public.fact_sales_settlement
    WHERE sales_channel_type = 'online'
      AND sales_order_id IS NOT NULL
    GROUP BY sales_order_id
),
fee_summary AS (
    SELECT
        sales_order_id,
        COUNT(*) AS fee_detail_rows,
        SUM(signed_fee_amount) AS signed_fee_amount
    FROM public.fact_sales_settlement_fee_detail
    WHERE sales_channel_type = 'online'
      AND sales_order_id IS NOT NULL
    GROUP BY sales_order_id
),
fulfillment_summary AS (
    SELECT
        sales_order_id,
        COUNT(*) AS fulfillment_rows,
        COUNT(*) FILTER (WHERE tracking_number IS NOT NULL) AS fulfillment_tracking_rows,
        COUNT(*) FILTER (WHERE delivered_at IS NOT NULL) AS fulfillment_delivered_rows,
        MIN(ready_to_ship_at) AS first_ready_to_ship_at,
        MIN(shipped_at) AS first_shipped_at,
        MAX(delivered_at) AS last_delivered_at
    FROM public.fact_sales_fulfillment
    WHERE sales_channel_type = 'online'
      AND sales_order_id IS NOT NULL
    GROUP BY sales_order_id
),
return_header_summary AS (
    SELECT
        sales_order_id,
        COUNT(*) AS return_rows,
        SUM(refund_amount) AS return_refund_amount,
        SUM(return_shipping_amount) AS return_shipping_amount,
        MIN(return_requested_at) AS first_return_requested_at,
        MAX(return_completed_at) AS last_return_completed_at
    FROM public.fact_sales_return
    WHERE sales_channel_type = 'online'
      AND sales_order_id IS NOT NULL
    GROUP BY sales_order_id
),
return_item_summary AS (
    SELECT
        fsr.sales_order_id,
        COUNT(*) AS return_item_rows,
        SUM(fsri.return_qty) AS return_qty,
        SUM(fsri.refund_item_amount) AS return_item_refund_amount
    FROM public.fact_sales_return_item fsri
    JOIN public.fact_sales_return fsr
        ON fsr.sales_return_id = fsri.sales_return_id
    WHERE fsr.sales_channel_type = 'online'
      AND fsr.sales_order_id IS NOT NULL
    GROUP BY fsr.sales_order_id
),
addon_summary AS (
    SELECT
        sales_order_id,
        COUNT(*) AS addon_rows,
        SUM(net_addon_amount) AS net_addon_amount
    FROM public.fact_sales_order_addon
    GROUP BY sales_order_id
)
SELECT
    fso.sales_order_id,
    fso.source_system,
    fso.sales_channel_type,
    fso.marketplace_id,
    dm.marketplace_name,
    fso.store_id,
    ds.store_name,
    fso.external_order_id,
    fso.external_order_group_id,
    fso.external_invoice_id,
    fso.order_date,
    fso.order_datetime,
    fso.order_status,
    fso.payment_status,
    fso.currency_code,
    fso.gross_order_amount,
    fso.discount_amount,
    fso.shipping_fee_amount,
    fso.net_order_amount,
    COALESCE(ss.settlement_rows, 0) AS settlement_rows,
    COALESCE(ss.settlement_amount, 0) AS settlement_amount,
    ss.first_settled_at,
    ss.last_settled_at,
    COALESCE(fs.fee_detail_rows, 0) AS fee_detail_rows,
    COALESCE(fs.signed_fee_amount, 0) AS signed_fee_amount,
    COALESCE(fuls.fulfillment_rows, 0) AS fulfillment_rows,
    COALESCE(fuls.fulfillment_tracking_rows, 0) AS fulfillment_tracking_rows,
    COALESCE(fuls.fulfillment_delivered_rows, 0) AS fulfillment_delivered_rows,
    fuls.first_ready_to_ship_at,
    fuls.first_shipped_at,
    fuls.last_delivered_at,
    COALESCE(rhs.return_rows, 0) AS return_rows,
    COALESCE(ris.return_item_rows, 0) AS return_item_rows,
    COALESCE(ris.return_qty, 0) AS return_qty,
    COALESCE(rhs.return_refund_amount, 0) AS return_refund_amount,
    COALESCE(ris.return_item_refund_amount, 0) AS return_item_refund_amount,
    COALESCE(rhs.return_shipping_amount, 0) AS return_shipping_amount,
    rhs.first_return_requested_at,
    rhs.last_return_completed_at,
    COALESCE(asum.addon_rows, 0) AS addon_rows,
    COALESCE(asum.net_addon_amount, 0) AS net_addon_amount,
    CASE
        WHEN COALESCE(inf.has_open_order_without_settlement_issue, false) THEN 'no_settlement_found'
        WHEN ss.sales_order_id IS NOT NULL THEN 'matched_to_settlement'
        ELSE 'not_evaluated'
    END AS reconciliation_status,
    CASE
        WHEN COALESCE(inf.has_open_order_without_fulfillment_issue, false) THEN 'no_fulfillment_found'
        WHEN fuls.sales_order_id IS NOT NULL THEN 'matched_to_fulfillment'
        ELSE 'not_evaluated'
    END AS fulfillment_reconciliation_status,
    COALESCE(inf.open_issue_count, 0) AS open_issue_count,
    COALESCE(inf.warning_issue_count, 0) AS warning_issue_count,
    fso.source_file,
    fso.source_sheet,
    fso.source_row_number,
    fso.raw_record_id,
    fso.notes
FROM public.fact_sales_order fso
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = fso.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = fso.store_id
LEFT JOIN settlement_summary ss
    ON ss.sales_order_id = fso.sales_order_id
LEFT JOIN fee_summary fs
    ON fs.sales_order_id = fso.sales_order_id
LEFT JOIN fulfillment_summary fuls
    ON fuls.sales_order_id = fso.sales_order_id
LEFT JOIN return_header_summary rhs
    ON rhs.sales_order_id = fso.sales_order_id
LEFT JOIN return_item_summary ris
    ON ris.sales_order_id = fso.sales_order_id
LEFT JOIN addon_summary asum
    ON asum.sales_order_id = fso.sales_order_id
LEFT JOIN issue_flags inf
    ON inf.sales_order_id = fso.sales_order_id;

CREATE OR REPLACE VIEW public.vw_sales_return_reconciliation AS
WITH issue_flags AS (
    SELECT
        sales_return_id,
        sales_return_item_id,
        COUNT(*) FILTER (WHERE issue_status = 'open') AS open_issue_count,
        COUNT(*) FILTER (WHERE issue_status = 'open' AND issue_severity = 'warning') AS warning_issue_count,
        BOOL_OR(issue_type = 'phase_return_without_order' AND issue_status = 'open') AS has_open_return_without_order_issue,
        BOOL_OR(issue_type = 'phase_return_item_without_order_item' AND issue_status = 'open') AS has_open_return_item_without_order_item_issue
    FROM public.data_quality_issue
    WHERE issue_domain = 'sales_money_flow'
      AND source_table IN ('fact_sales_return', 'fact_sales_return_item')
    GROUP BY sales_return_id, sales_return_item_id
)
SELECT
    fsr.sales_return_id,
    fsri.sales_return_item_id,
    fsr.source_system,
    fsr.sales_channel_type,
    fsr.marketplace_id,
    dm.marketplace_name,
    fsr.store_id,
    ds.store_name,
    fsr.sales_order_id,
    fsri.sales_order_item_id,
    fsr.external_order_id,
    fsr.external_return_id,
    fsri.source_line_id,
    fsri.source_sku_code,
    fsri.source_product_name,
    fsri.source_variation_name,
    fsri.product_id,
    fsri.product_sku_alias_id,
    fsr.return_type,
    fsr.return_status,
    fsr.return_reason,
    fsr.return_initiator,
    fsr.return_requested_at,
    fsr.return_completed_at,
    fsri.return_qty,
    fsr.refund_amount,
    fsri.refund_item_amount,
    fsr.return_shipping_amount,
    fsr.currency_code,
    CASE
        WHEN fsr.sales_order_id IS NULL THEN 'missing_order_reference'
        WHEN fsri.sales_return_item_id IS NOT NULL
         AND fsri.sales_order_item_id IS NULL THEN 'missing_order_item_reference'
        WHEN fsri.sales_return_item_id IS NOT NULL THEN 'matched_to_order_and_item'
        ELSE 'matched_to_order_header_only'
    END AS reconciliation_status,
    COALESCE(inf_item.open_issue_count, inf_header.open_issue_count, 0) AS open_issue_count,
    COALESCE(inf_item.warning_issue_count, inf_header.warning_issue_count, 0) AS warning_issue_count,
    COALESCE(fsr.source_file, fsri.source_file) AS source_file,
    COALESCE(fsr.source_sheet, fsri.source_sheet) AS source_sheet,
    COALESCE(fsr.source_row_number, fsri.source_row_number) AS source_row_number,
    COALESCE(fsr.raw_record_id, fsri.raw_record_id) AS raw_record_id,
    fsr.notes
FROM public.fact_sales_return fsr
LEFT JOIN public.fact_sales_return_item fsri
    ON fsri.sales_return_id = fsr.sales_return_id
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = fsr.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = fsr.store_id
LEFT JOIN issue_flags inf_header
    ON inf_header.sales_return_id = fsr.sales_return_id
   AND inf_header.sales_return_item_id IS NULL
LEFT JOIN issue_flags inf_item
    ON inf_item.sales_return_item_id = fsri.sales_return_item_id;

CREATE OR REPLACE VIEW public.vw_sales_fulfillment_reconciliation AS
WITH issue_flags AS (
    SELECT
        sales_fulfillment_id,
        BOOL_OR(issue_type = 'phase_fulfillment_without_order' AND issue_status = 'open') AS has_open_fulfillment_without_order_issue,
        COUNT(*) FILTER (WHERE issue_status = 'open') AS open_issue_count,
        COUNT(*) FILTER (WHERE issue_status = 'open' AND issue_severity = 'warning') AS warning_issue_count
    FROM public.data_quality_issue
    WHERE issue_domain = 'sales_money_flow'
      AND source_table = 'fact_sales_fulfillment'
    GROUP BY sales_fulfillment_id
)
SELECT
    fsf.sales_fulfillment_id,
    fsf.source_system,
    fsf.sales_channel_type,
    fsf.marketplace_id,
    dm.marketplace_name,
    fsf.store_id,
    ds.store_name,
    fsf.sales_order_id,
    fsf.external_order_id,
    fsf.external_order_group_id,
    fsf.external_fulfillment_id,
    fsf.external_package_id,
    fsf.tracking_number,
    fsf.tracking_url,
    fsf.warehouse_id,
    fsf.source_warehouse_name,
    fsf.shipping_service_id,
    fsf.source_shipping_provider,
    fsf.source_shipping_service,
    fsf.source_shipping_service_level,
    fsf.fulfillment_status,
    fsf.logistics_status,
    fsf.handover_type,
    fsf.is_dropship,
    fsf.order_created_at,
    fsf.paid_at,
    fsf.ready_to_ship_at,
    fsf.target_shipped_at,
    fsf.pickup_at,
    fsf.handover_at,
    fsf.shipped_at,
    fsf.delivered_at,
    fsf.cancelled_at,
    fsf.returned_at,
    fsf.weight_kg,
    fsf.distance_fee_amount,
    fsf.shipping_fee_amount,
    fsf.currency_code,
    fsf.destination_location_id,
    fsf.destination_city,
    fsf.destination_province,
    fsf.destination_postal_code,
    fsf.destination_country,
    CASE
        WHEN COALESCE(inf.has_open_fulfillment_without_order_issue, false) THEN 'missing_order_reference'
        WHEN fsf.sales_order_id IS NOT NULL THEN 'matched_to_order'
        ELSE 'not_evaluated'
    END AS reconciliation_status,
    CASE
        WHEN fsf.delivered_at IS NOT NULL THEN 'delivered'
        WHEN fsf.shipped_at IS NOT NULL THEN 'shipped'
        WHEN fsf.ready_to_ship_at IS NOT NULL THEN 'ready_to_ship'
        WHEN fsf.paid_at IS NOT NULL THEN 'paid'
        WHEN fsf.cancelled_at IS NOT NULL THEN 'cancelled'
        ELSE 'unknown'
    END AS fulfillment_lifecycle_status,
    COALESCE(inf.open_issue_count, 0) AS open_issue_count,
    COALESCE(inf.warning_issue_count, 0) AS warning_issue_count,
    fsf.source_file,
    fsf.source_sheet,
    fsf.source_row_number,
    fsf.raw_record_id,
    fsf.notes
FROM public.fact_sales_fulfillment fsf
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = fsf.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = fsf.store_id
LEFT JOIN issue_flags inf
    ON inf.sales_fulfillment_id = fsf.sales_fulfillment_id;

CREATE OR REPLACE VIEW public.vw_sales_settlement_reconciliation AS
WITH issue_flags AS (
    SELECT
        sales_settlement_id,
        BOOL_OR(issue_type = 'phase2_settlement_without_order' AND issue_status = 'open') AS has_open_settlement_without_order_issue,
        COUNT(*) FILTER (WHERE issue_status = 'open') AS open_issue_count,
        COUNT(*) FILTER (WHERE issue_status = 'open' AND issue_severity = 'warning') AS warning_issue_count
    FROM public.data_quality_issue
    WHERE issue_domain = 'sales_money_flow'
      AND source_table = 'fact_sales_settlement'
    GROUP BY sales_settlement_id
),
fee_summary AS (
    SELECT
        sales_settlement_id,
        COUNT(*) AS fee_detail_rows,
        SUM(signed_fee_amount) AS signed_fee_amount
    FROM public.fact_sales_settlement_fee_detail
    WHERE sales_channel_type = 'online'
      AND sales_settlement_id IS NOT NULL
    GROUP BY sales_settlement_id
),
adjustment_summary AS (
    SELECT
        sales_settlement_id,
        COUNT(*) AS adjustment_rows,
        SUM(signed_adjustment_amount) AS signed_adjustment_amount
    FROM public.fact_sales_settlement_adjustment
    WHERE sales_channel_type = 'online'
      AND sales_settlement_id IS NOT NULL
    GROUP BY sales_settlement_id
),
balance_summary AS (
    SELECT
        sales_settlement_id,
        COUNT(*) AS balance_rows,
        SUM(signed_amount) AS balance_signed_amount
    FROM public.fact_balance_transaction
    WHERE sales_channel_type = 'online'
      AND sales_settlement_id IS NOT NULL
    GROUP BY sales_settlement_id
)
SELECT
    fss.sales_settlement_id,
    fss.source_system,
    fss.sales_channel_type,
    fss.marketplace_id,
    dm.marketplace_name,
    fss.store_id,
    ds.store_name,
    fss.sales_order_id,
    fss.external_order_id,
    fss.external_order_item_id,
    fss.source_sku_code,
    fss.settlement_type,
    fss.order_created_at,
    fss.settled_at,
    fss.released_at,
    fss.settlement_status,
    fss.currency_code,
    fss.gross_revenue_amount,
    fss.refund_amount,
    fss.seller_discount_amount,
    fss.platform_discount_amount,
    fss.shipping_amount,
    fss.total_fee_amount,
    fss.settlement_amount,
    COALESCE(fs.fee_detail_rows, 0) AS fee_detail_rows,
    COALESCE(fs.signed_fee_amount, 0) AS signed_fee_amount,
    COALESCE(adjs.adjustment_rows, 0) AS adjustment_rows,
    COALESCE(adjs.signed_adjustment_amount, 0) AS signed_adjustment_amount,
    COALESCE(bs.balance_rows, 0) AS balance_rows,
    COALESCE(bs.balance_signed_amount, 0) AS balance_signed_amount,
    CASE
        WHEN COALESCE(inf.has_open_settlement_without_order_issue, false) THEN 'missing_order_source'
        WHEN fss.sales_order_id IS NOT NULL THEN 'matched_to_order'
        ELSE 'not_evaluated'
    END AS reconciliation_status,
    COALESCE(inf.open_issue_count, 0) AS open_issue_count,
    COALESCE(inf.warning_issue_count, 0) AS warning_issue_count,
    fss.source_file,
    fss.source_sheet,
    fss.source_row_number,
    fss.raw_record_id,
    fss.notes
FROM public.fact_sales_settlement fss
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = fss.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = fss.store_id
LEFT JOIN issue_flags inf
    ON inf.sales_settlement_id = fss.sales_settlement_id
LEFT JOIN fee_summary fs
    ON fs.sales_settlement_id = fss.sales_settlement_id
LEFT JOIN adjustment_summary adjs
    ON adjs.sales_settlement_id = fss.sales_settlement_id
LEFT JOIN balance_summary bs
    ON bs.sales_settlement_id = fss.sales_settlement_id;

CREATE OR REPLACE VIEW public.vw_sales_balance_reconciliation AS
WITH issue_flags AS (
    SELECT
        balance_transaction_id,
        BOOL_OR(issue_type = 'phase5_balance_order_id_without_order_match' AND issue_status = 'open') AS has_open_missing_order_issue,
        BOOL_OR(issue_type = 'phase5_balance_order_id_without_settlement_match' AND issue_status = 'open') AS has_open_missing_settlement_issue,
        COUNT(*) FILTER (WHERE issue_status = 'open') AS open_issue_count,
        COUNT(*) FILTER (WHERE issue_status = 'open' AND issue_severity = 'warning') AS warning_issue_count
    FROM public.data_quality_issue
    WHERE issue_domain = 'sales_money_flow'
      AND source_table = 'fact_balance_transaction'
    GROUP BY balance_transaction_id
)
SELECT
    fbt.balance_transaction_id,
    fbt.source_system,
    fbt.sales_channel_type,
    fbt.marketplace_id,
    dm.marketplace_name,
    fbt.store_id,
    ds.store_name,
    fbt.sales_order_id,
    fbt.sales_settlement_id,
    fbt.external_transaction_id,
    fbt.external_order_id,
    fbt.transaction_type,
    fbt.transaction_sub_type,
    fbt.transaction_status,
    fbt.transaction_description,
    fbt.transaction_description_key,
    fbt.movement_direction,
    fbt.raw_amount,
    fbt.signed_amount,
    fbt.amount_sign_from_source,
    fbt.balance_after_amount,
    fbt.currency_code,
    fbt.transaction_occurred_at,
    fbt.transaction_requested_at,
    fbt.transaction_succeeded_at,
    fbt.bank_account,
    CASE
        WHEN COALESCE(inf.has_open_missing_order_issue, false)
         AND COALESCE(inf.has_open_missing_settlement_issue, false)
            THEN 'missing_order_and_settlement_reference'
        WHEN COALESCE(inf.has_open_missing_order_issue, false)
            THEN 'missing_order_reference'
        WHEN COALESCE(inf.has_open_missing_settlement_issue, false)
            THEN 'missing_settlement_reference'
        WHEN fbt.sales_order_id IS NOT NULL
         AND fbt.sales_settlement_id IS NOT NULL
            THEN 'matched_to_order_and_settlement'
        WHEN fbt.sales_order_id IS NOT NULL
            THEN 'matched_to_order_only'
        WHEN fbt.sales_settlement_id IS NOT NULL
            THEN 'matched_to_settlement_only'
        WHEN fbt.external_order_id IS NULL
            THEN 'non_order_balance_movement'
        ELSE 'not_evaluated'
    END AS reconciliation_status,
    COALESCE(inf.open_issue_count, 0) AS open_issue_count,
    COALESCE(inf.warning_issue_count, 0) AS warning_issue_count,
    fbt.source_table,
    fbt.source_file,
    fbt.source_sheet,
    fbt.source_row_number,
    fbt.raw_record_id,
    fbt.notes
FROM public.fact_balance_transaction fbt
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = fbt.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = fbt.store_id
LEFT JOIN issue_flags inf
    ON inf.balance_transaction_id = fbt.balance_transaction_id;

CREATE OR REPLACE VIEW public.vw_sales_money_flow_summary AS
WITH order_summary AS (
    SELECT
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', COALESCE(order_datetime, order_date::timestamptz))::date AS period_month,
        COUNT(*) AS order_rows,
        SUM(gross_order_amount) AS gross_order_amount,
        SUM(discount_amount) AS order_discount_amount,
        SUM(shipping_fee_amount) AS order_shipping_amount,
        SUM(net_order_amount) AS net_order_amount
    FROM public.fact_sales_order
    WHERE sales_channel_type = 'online'
    GROUP BY source_system, marketplace_id, store_id, date_trunc('month', COALESCE(order_datetime, order_date::timestamptz))::date
),
settlement_summary AS (
    SELECT
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', COALESCE(released_at, settled_at, order_created_at))::date AS period_month,
        COUNT(*) AS settlement_rows,
        COUNT(sales_order_id) AS settlement_matched_order_rows,
        SUM(gross_revenue_amount) AS settlement_gross_revenue_amount,
        SUM(refund_amount) AS settlement_refund_amount,
        SUM(total_fee_amount) AS settlement_total_fee_amount,
        SUM(settlement_amount) AS settlement_amount
    FROM public.fact_sales_settlement
    WHERE sales_channel_type = 'online'
    GROUP BY source_system, marketplace_id, store_id, date_trunc('month', COALESCE(released_at, settled_at, order_created_at))::date
),
fee_summary AS (
    SELECT
        fsfd.source_system,
        fsfd.marketplace_id,
        fsfd.store_id,
        date_trunc(
            'month',
            COALESCE(fss.released_at, fss.settled_at, fss.order_created_at, fsfd.created_at)
        )::date AS period_month,
        COUNT(*) AS fee_detail_rows,
        SUM(fsfd.signed_fee_amount) AS signed_fee_amount
    FROM public.fact_sales_settlement_fee_detail fsfd
    LEFT JOIN public.fact_sales_settlement fss
        ON fss.sales_settlement_id = fsfd.sales_settlement_id
    WHERE fsfd.sales_channel_type = 'online'
    GROUP BY
        fsfd.source_system,
        fsfd.marketplace_id,
        fsfd.store_id,
        date_trunc(
            'month',
            COALESCE(fss.released_at, fss.settled_at, fss.order_created_at, fsfd.created_at)
        )::date
),
adjustment_summary AS (
    SELECT
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', adjustment_occurred_at)::date AS period_month,
        COUNT(*) AS adjustment_rows,
        SUM(signed_adjustment_amount) AS signed_adjustment_amount
    FROM public.fact_sales_settlement_adjustment
    WHERE sales_channel_type = 'online'
    GROUP BY source_system, marketplace_id, store_id, date_trunc('month', adjustment_occurred_at)::date
),
return_summary AS (
    SELECT
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', COALESCE(return_completed_at, return_requested_at, created_at))::date AS period_month,
        COUNT(*) AS return_rows,
        COUNT(sales_order_id) AS return_matched_order_rows,
        SUM(refund_amount) AS return_refund_amount,
        SUM(return_shipping_amount) AS return_shipping_amount
    FROM public.fact_sales_return
    WHERE sales_channel_type = 'online'
    GROUP BY
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', COALESCE(return_completed_at, return_requested_at, created_at))::date
),
return_item_summary AS (
    SELECT
        fsr.source_system,
        fsr.marketplace_id,
        fsr.store_id,
        date_trunc('month', COALESCE(fsr.return_completed_at, fsr.return_requested_at, fsr.created_at))::date AS period_month,
        COUNT(*) AS return_item_rows,
        COUNT(fsri.sales_order_item_id) AS return_item_matched_order_item_rows,
        SUM(fsri.return_qty) AS return_qty,
        SUM(fsri.refund_item_amount) AS return_item_refund_amount
    FROM public.fact_sales_return_item fsri
    JOIN public.fact_sales_return fsr
        ON fsr.sales_return_id = fsri.sales_return_id
    WHERE fsr.sales_channel_type = 'online'
    GROUP BY
        fsr.source_system,
        fsr.marketplace_id,
        fsr.store_id,
        date_trunc('month', COALESCE(fsr.return_completed_at, fsr.return_requested_at, fsr.created_at))::date
),
fulfillment_summary AS (
    SELECT
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', COALESCE(paid_at, order_created_at, ready_to_ship_at, shipped_at, delivered_at, created_at))::date AS period_month,
        COUNT(*) AS fulfillment_rows,
        COUNT(sales_order_id) AS fulfillment_matched_order_rows,
        COUNT(*) FILTER (WHERE tracking_number IS NOT NULL) AS fulfillment_tracking_rows,
        COUNT(*) FILTER (WHERE delivered_at IS NOT NULL) AS fulfillment_delivered_rows,
        SUM(weight_kg) AS fulfillment_weight_kg,
        SUM(distance_fee_amount) AS fulfillment_distance_fee_amount,
        SUM(shipping_fee_amount) AS fulfillment_shipping_fee_amount
    FROM public.fact_sales_fulfillment
    WHERE sales_channel_type = 'online'
    GROUP BY
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', COALESCE(paid_at, order_created_at, ready_to_ship_at, shipped_at, delivered_at, created_at))::date
),
balance_summary AS (
    SELECT
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', transaction_occurred_at)::date AS period_month,
        COUNT(*) AS balance_rows,
        COUNT(*) FILTER (WHERE movement_direction = 'credit') AS balance_credit_rows,
        COUNT(*) FILTER (WHERE movement_direction = 'debit') AS balance_debit_rows,
        SUM(signed_amount) AS balance_signed_amount,
        SUM(signed_amount) FILTER (WHERE movement_direction = 'credit') AS balance_credit_amount,
        SUM(signed_amount) FILTER (WHERE movement_direction = 'debit') AS balance_debit_amount
    FROM public.fact_balance_transaction
    WHERE sales_channel_type = 'online'
    GROUP BY source_system, marketplace_id, store_id, date_trunc('month', transaction_occurred_at)::date
),
issue_summary AS (
    SELECT
        source_system,
        marketplace_id,
        store_id,
        date_trunc('month', issue_occurred_at)::date AS period_month,
        COUNT(*) FILTER (WHERE issue_status = 'open') AS open_issue_count,
        COUNT(*) FILTER (WHERE issue_status = 'open' AND issue_severity = 'warning') AS warning_issue_count,
        COUNT(*) FILTER (WHERE issue_status = 'open' AND issue_severity = 'critical') AS critical_issue_count
    FROM public.data_quality_issue
    WHERE issue_domain = 'sales_money_flow'
    GROUP BY source_system, marketplace_id, store_id, date_trunc('month', issue_occurred_at)::date
),
all_keys AS (
    SELECT source_system, marketplace_id, store_id, period_month FROM order_summary
    UNION
    SELECT source_system, marketplace_id, store_id, period_month FROM settlement_summary
    UNION
    SELECT source_system, marketplace_id, store_id, period_month FROM fee_summary
    UNION
    SELECT source_system, marketplace_id, store_id, period_month FROM adjustment_summary
    UNION
    SELECT source_system, marketplace_id, store_id, period_month FROM return_summary
    UNION
    SELECT source_system, marketplace_id, store_id, period_month FROM return_item_summary
    UNION
    SELECT source_system, marketplace_id, store_id, period_month FROM fulfillment_summary
    UNION
    SELECT source_system, marketplace_id, store_id, period_month FROM balance_summary
    UNION
    SELECT source_system, marketplace_id, store_id, period_month FROM issue_summary
)
SELECT
    ak.source_system,
    ak.marketplace_id,
    dm.marketplace_name,
    ak.store_id,
    ds.store_name,
    ak.period_month,
    COALESCE(os.order_rows, 0) AS order_rows,
    COALESCE(os.gross_order_amount, 0) AS gross_order_amount,
    COALESCE(os.order_discount_amount, 0) AS order_discount_amount,
    COALESCE(os.order_shipping_amount, 0) AS order_shipping_amount,
    COALESCE(os.net_order_amount, 0) AS net_order_amount,
    COALESCE(ss.settlement_rows, 0) AS settlement_rows,
    COALESCE(ss.settlement_matched_order_rows, 0) AS settlement_matched_order_rows,
    COALESCE(ss.settlement_gross_revenue_amount, 0) AS settlement_gross_revenue_amount,
    COALESCE(ss.settlement_refund_amount, 0) AS settlement_refund_amount,
    COALESCE(ss.settlement_total_fee_amount, 0) AS settlement_total_fee_amount,
    COALESCE(ss.settlement_amount, 0) AS settlement_amount,
    COALESCE(fs.fee_detail_rows, 0) AS fee_detail_rows,
    COALESCE(fs.signed_fee_amount, 0) AS signed_fee_amount,
    COALESCE(adjs.adjustment_rows, 0) AS adjustment_rows,
    COALESCE(adjs.signed_adjustment_amount, 0) AS signed_adjustment_amount,
    COALESCE(rs.return_rows, 0) AS return_rows,
    COALESCE(rs.return_matched_order_rows, 0) AS return_matched_order_rows,
    COALESCE(ris.return_item_rows, 0) AS return_item_rows,
    COALESCE(ris.return_item_matched_order_item_rows, 0) AS return_item_matched_order_item_rows,
    COALESCE(ris.return_qty, 0) AS return_qty,
    COALESCE(rs.return_refund_amount, 0) AS return_refund_amount,
    COALESCE(ris.return_item_refund_amount, 0) AS return_item_refund_amount,
    COALESCE(rs.return_shipping_amount, 0) AS return_shipping_amount,
    COALESCE(fuls.fulfillment_rows, 0) AS fulfillment_rows,
    COALESCE(fuls.fulfillment_matched_order_rows, 0) AS fulfillment_matched_order_rows,
    COALESCE(fuls.fulfillment_tracking_rows, 0) AS fulfillment_tracking_rows,
    COALESCE(fuls.fulfillment_delivered_rows, 0) AS fulfillment_delivered_rows,
    COALESCE(fuls.fulfillment_weight_kg, 0) AS fulfillment_weight_kg,
    COALESCE(fuls.fulfillment_distance_fee_amount, 0) AS fulfillment_distance_fee_amount,
    COALESCE(fuls.fulfillment_shipping_fee_amount, 0) AS fulfillment_shipping_fee_amount,
    COALESCE(bs.balance_rows, 0) AS balance_rows,
    COALESCE(bs.balance_credit_rows, 0) AS balance_credit_rows,
    COALESCE(bs.balance_debit_rows, 0) AS balance_debit_rows,
    COALESCE(bs.balance_signed_amount, 0) AS balance_signed_amount,
    COALESCE(bs.balance_credit_amount, 0) AS balance_credit_amount,
    COALESCE(bs.balance_debit_amount, 0) AS balance_debit_amount,
    COALESCE(iss.open_issue_count, 0) AS open_issue_count,
    COALESCE(iss.warning_issue_count, 0) AS warning_issue_count,
    COALESCE(iss.critical_issue_count, 0) AS critical_issue_count
FROM all_keys ak
LEFT JOIN public.dim_marketplace dm
    ON dm.marketplace_id = ak.marketplace_id
LEFT JOIN public.dim_store ds
    ON ds.store_id = ak.store_id
LEFT JOIN order_summary os
    ON os.source_system = ak.source_system
   AND os.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND os.store_id IS NOT DISTINCT FROM ak.store_id
   AND os.period_month IS NOT DISTINCT FROM ak.period_month
LEFT JOIN settlement_summary ss
    ON ss.source_system = ak.source_system
   AND ss.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND ss.store_id IS NOT DISTINCT FROM ak.store_id
   AND ss.period_month IS NOT DISTINCT FROM ak.period_month
LEFT JOIN fee_summary fs
    ON fs.source_system = ak.source_system
   AND fs.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND fs.store_id IS NOT DISTINCT FROM ak.store_id
   AND fs.period_month IS NOT DISTINCT FROM ak.period_month
LEFT JOIN adjustment_summary adjs
    ON adjs.source_system = ak.source_system
   AND adjs.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND adjs.store_id IS NOT DISTINCT FROM ak.store_id
   AND adjs.period_month IS NOT DISTINCT FROM ak.period_month
LEFT JOIN return_summary rs
    ON rs.source_system = ak.source_system
   AND rs.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND rs.store_id IS NOT DISTINCT FROM ak.store_id
   AND rs.period_month IS NOT DISTINCT FROM ak.period_month
LEFT JOIN return_item_summary ris
    ON ris.source_system = ak.source_system
   AND ris.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND ris.store_id IS NOT DISTINCT FROM ak.store_id
   AND ris.period_month IS NOT DISTINCT FROM ak.period_month
LEFT JOIN fulfillment_summary fuls
    ON fuls.source_system = ak.source_system
   AND fuls.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND fuls.store_id IS NOT DISTINCT FROM ak.store_id
   AND fuls.period_month IS NOT DISTINCT FROM ak.period_month
LEFT JOIN balance_summary bs
    ON bs.source_system = ak.source_system
   AND bs.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND bs.store_id IS NOT DISTINCT FROM ak.store_id
   AND bs.period_month IS NOT DISTINCT FROM ak.period_month
LEFT JOIN issue_summary iss
    ON iss.source_system = ak.source_system
   AND iss.marketplace_id IS NOT DISTINCT FROM ak.marketplace_id
   AND iss.store_id IS NOT DISTINCT FROM ak.store_id
   AND iss.period_month IS NOT DISTINCT FROM ak.period_month;

COMMIT;
