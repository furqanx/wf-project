-- Read-only final audit for marketplace fee semantics and reconciliation.
-- Temporary tables avoid repeatedly evaluating canonical order views.

\pset pager off
\set ON_ERROR_STOP on

SET statement_timeout = '30min';
SET lock_timeout = '10s';

BEGIN;

CREATE TEMP TABLE tmp_mpf_order_classification ON COMMIT DROP AS
SELECT
    sales_order_id,
    source_system,
    marketplace_id,
    store_id,
    external_order_id,
    order_date,
    net_order_amount,
    product_quantity_signature,
    order_status,
    is_analytics_included,
    CASE
        WHEN LOWER(COALESCE(order_status, '')) IN (
            'batal', 'canceled', 'cancelled', 'dibatalkan'
        ) THEN FALSE
        ELSE TRUE
    END AS is_valid_order
FROM public.vw_sales_order_channel_classification
WHERE source_system IN ('shopee', 'lazada', 'tiktok_tokopedia');

CREATE INDEX ON tmp_mpf_order_classification (sales_order_id);
CREATE INDEX ON tmp_mpf_order_classification (
    source_system,
    external_order_id,
    net_order_amount,
    product_quantity_signature
);
ANALYZE tmp_mpf_order_classification;

CREATE TEMP TABLE tmp_mpf_order_resolution ON COMMIT DROP AS
SELECT
    candidate.sales_order_id AS source_sales_order_id,
    canonical.sales_order_id AS canonical_sales_order_id
FROM tmp_mpf_order_classification candidate
JOIN tmp_mpf_order_classification canonical
    ON canonical.source_system = candidate.source_system
   AND canonical.external_order_id = candidate.external_order_id
   AND COALESCE(canonical.net_order_amount, 0) = COALESCE(candidate.net_order_amount, 0)
   AND canonical.product_quantity_signature = candidate.product_quantity_signature
   AND canonical.is_analytics_included = TRUE;

CREATE UNIQUE INDEX ON tmp_mpf_order_resolution (source_sales_order_id);
CREATE INDEX ON tmp_mpf_order_resolution (canonical_sales_order_id);
ANALYZE tmp_mpf_order_resolution;

CREATE TEMP TABLE tmp_mpf_fee ON COMMIT DROP AS
SELECT
    fees.sales_settlement_fee_detail_id,
    fees.source_system,
    fees.marketplace_id,
    fees.store_id,
    fees.sales_order_id AS source_sales_order_id,
    resolution.canonical_sales_order_id,
    fees.sales_settlement_id,
    fees.external_order_id,
    fees.external_order_item_id,
    fees.source_sku_code,
    fees.fee_grain_type,
    fees.raw_fee_name,
    fees.raw_fee_amount,
    fees.signed_fee_amount,
    fees.sign_rule,
    fees.sign_confidence,
    fees.raw_record_id,
    types.fee_type_id,
    types.fee_code,
    types.fee_name,
    types.fee_category,
    types.amount_behavior,
    types.is_platform_fee,
    orders.order_date,
    orders.net_order_amount,
    orders.is_valid_order
FROM public.fact_sales_settlement_fee_detail fees
JOIN public.fee_type types
    ON types.fee_type_id = fees.fee_type_id
LEFT JOIN tmp_mpf_order_resolution resolution
    ON resolution.source_sales_order_id = fees.sales_order_id
LEFT JOIN tmp_mpf_order_classification orders
    ON orders.sales_order_id = resolution.canonical_sales_order_id
WHERE fees.is_active = TRUE;

CREATE INDEX ON tmp_mpf_fee (sales_settlement_id);
CREATE INDEX ON tmp_mpf_fee (canonical_sales_order_id);
CREATE INDEX ON tmp_mpf_fee (source_system, fee_category, amount_behavior);
ANALYZE tmp_mpf_fee;

-- A. Fee direction and governed behavior by source/category.
SELECT
    source_system,
    fee_category,
    amount_behavior,
    COUNT(*) AS fee_rows,
    COUNT(*) FILTER (WHERE signed_fee_amount < 0) AS deduction_rows,
    COUNT(*) FILTER (WHERE signed_fee_amount > 0) AS addition_rows,
    COUNT(*) FILTER (WHERE signed_fee_amount = 0) AS zero_rows,
    SUM(signed_fee_amount) AS net_signed_amount,
    SUM(ABS(signed_fee_amount)) FILTER (WHERE signed_fee_amount < 0) AS deduction_amount,
    SUM(signed_fee_amount) FILTER (WHERE signed_fee_amount > 0) AS addition_amount
FROM tmp_mpf_fee
GROUP BY source_system, fee_category, amount_behavior
ORDER BY source_system, fee_category, amount_behavior;

-- B. Sign-policy violations. Any non-zero result requires fee master review.
SELECT
    source_system,
    amount_behavior,
    COUNT(*) FILTER (
        WHERE amount_behavior = 'deduction' AND signed_fee_amount > 0
    ) AS deduction_with_positive_sign,
    COUNT(*) FILTER (
        WHERE amount_behavior = 'addition' AND signed_fee_amount < 0
    ) AS addition_with_negative_sign,
    COUNT(*) FILTER (
        WHERE amount_behavior = 'zero_or_unused' AND signed_fee_amount <> 0
    ) AS zero_or_unused_with_value,
    SUM(ABS(signed_fee_amount)) FILTER (
        WHERE (amount_behavior = 'deduction' AND signed_fee_amount > 0)
           OR (amount_behavior = 'addition' AND signed_fee_amount < 0)
           OR (amount_behavior = 'zero_or_unused' AND signed_fee_amount <> 0)
    ) AS violation_amount
FROM tmp_mpf_fee
GROUP BY source_system, amount_behavior
ORDER BY source_system, amount_behavior;

-- C. Detailed fee-type behavior, including logistics/pass-through candidates.
SELECT
    source_system,
    fee_type_id,
    fee_code,
    fee_name,
    fee_category,
    amount_behavior,
    is_platform_fee,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT canonical_sales_order_id) AS canonical_orders,
    SUM(signed_fee_amount) AS net_signed_amount,
    SUM(ABS(signed_fee_amount)) FILTER (WHERE signed_fee_amount < 0) AS deduction_amount,
    SUM(signed_fee_amount) FILTER (WHERE signed_fee_amount > 0) AS addition_amount
FROM tmp_mpf_fee
GROUP BY
    source_system,
    fee_type_id,
    fee_code,
    fee_name,
    fee_category,
    amount_behavior,
    is_platform_fee
ORDER BY source_system, ABS(SUM(signed_fee_amount)) DESC, fee_type_id;

\copy (SELECT source_system, fee_type_id, fee_code, fee_name, fee_category, amount_behavior, is_platform_fee, COUNT(*) AS fee_rows, COUNT(DISTINCT canonical_sales_order_id) AS canonical_orders, SUM(signed_fee_amount) AS net_signed_amount, SUM(ABS(signed_fee_amount)) FILTER (WHERE signed_fee_amount < 0) AS deduction_amount, SUM(signed_fee_amount) FILTER (WHERE signed_fee_amount > 0) AS addition_amount FROM tmp_mpf_fee GROUP BY source_system, fee_type_id, fee_code, fee_name, fee_category, amount_behavior, is_platform_fee ORDER BY source_system, ABS(SUM(signed_fee_amount)) DESC, fee_type_id) TO '/tmp/sales_marketplace_fee_type_semantics.csv' WITH (FORMAT CSV, HEADER TRUE)

-- D. Reconcile settlement header total fee with fee detail by settlement.
CREATE TEMP TABLE tmp_mpf_settlement_reconciliation ON COMMIT DROP AS
WITH fee_detail AS (
    SELECT
        sales_settlement_id,
        COUNT(*) AS fee_rows,
        SUM(signed_fee_amount) AS detail_signed_fee_amount
    FROM tmp_mpf_fee
    WHERE sales_settlement_id IS NOT NULL
    GROUP BY sales_settlement_id
)
SELECT
    settlements.source_system,
    settlements.sales_settlement_id,
    settlements.sales_order_id,
    settlements.external_order_id,
    settlements.store_id,
    settlements.total_fee_amount AS header_fee_amount,
    details.fee_rows,
    details.detail_signed_fee_amount,
    ABS(COALESCE(settlements.total_fee_amount, 0))
        - ABS(COALESCE(details.detail_signed_fee_amount, 0)) AS absolute_amount_delta,
    CASE
        WHEN settlements.total_fee_amount IS NULL THEN 'header_fee_unavailable'
        WHEN details.sales_settlement_id IS NULL THEN 'detail_fee_unavailable'
        WHEN ABS(
            ABS(COALESCE(settlements.total_fee_amount, 0))
            - ABS(COALESCE(details.detail_signed_fee_amount, 0))
        ) <= 0.01 THEN 'reconciled'
        ELSE 'amount_mismatch'
    END AS reconciliation_status
FROM public.fact_sales_settlement settlements
LEFT JOIN fee_detail details
    ON details.sales_settlement_id = settlements.sales_settlement_id
WHERE settlements.is_active = TRUE;

SELECT
    source_system,
    reconciliation_status,
    COUNT(*) AS settlement_rows,
    SUM(header_fee_amount) AS header_fee_amount,
    SUM(detail_signed_fee_amount) AS detail_signed_fee_amount,
    SUM(ABS(absolute_amount_delta)) AS absolute_delta
FROM tmp_mpf_settlement_reconciliation
GROUP BY source_system, reconciliation_status
ORDER BY source_system, reconciliation_status;

\copy (SELECT * FROM tmp_mpf_settlement_reconciliation WHERE reconciliation_status = 'amount_mismatch' ORDER BY source_system, ABS(absolute_amount_delta) DESC, sales_settlement_id) TO '/tmp/sales_marketplace_fee_header_detail_mismatch.csv' WITH (FORMAT CSV, HEADER TRUE)

-- E. Potential repeated fee components at the same business grain.
WITH repeated_components AS (
    SELECT
        source_system,
        sales_settlement_id,
        canonical_sales_order_id,
        fee_type_id,
        COALESCE(external_order_item_id, '') AS external_order_item_id,
        COALESCE(source_sku_code, '') AS source_sku_code,
        raw_fee_name,
        signed_fee_amount,
        COUNT(*) AS repeated_rows
    FROM tmp_mpf_fee
    GROUP BY
        source_system,
        sales_settlement_id,
        canonical_sales_order_id,
        fee_type_id,
        COALESCE(external_order_item_id, ''),
        COALESCE(source_sku_code, ''),
        raw_fee_name,
        signed_fee_amount
    HAVING COUNT(*) > 1
)
SELECT
    source_system,
    COUNT(*) AS repeated_component_grains,
    SUM(repeated_rows) AS repeated_rows,
    SUM((repeated_rows - 1) * ABS(signed_fee_amount)) AS potential_extra_amount
FROM repeated_components
GROUP BY source_system
ORDER BY source_system;

-- F. Monthly/store fee-to-revenue ratios and coverage.
CREATE TEMP TABLE tmp_mpf_order_fee ON COMMIT DROP AS
SELECT
    orders.sales_order_id,
    orders.source_system,
    orders.store_id,
    orders.order_date,
    orders.net_order_amount,
    COUNT(fees.sales_settlement_fee_detail_id) AS fee_rows,
    SUM(fees.signed_fee_amount) AS net_signed_fee_amount,
    SUM(ABS(fees.signed_fee_amount)) FILTER (
        WHERE fees.signed_fee_amount < 0
    ) AS deduction_amount,
    SUM(fees.signed_fee_amount) FILTER (
        WHERE fees.signed_fee_amount > 0
    ) AS addition_amount
FROM tmp_mpf_order_classification orders
LEFT JOIN tmp_mpf_fee fees
    ON fees.canonical_sales_order_id = orders.sales_order_id
WHERE orders.is_analytics_included = TRUE
  AND orders.is_valid_order = TRUE
GROUP BY
    orders.sales_order_id,
    orders.source_system,
    orders.store_id,
    orders.order_date,
    orders.net_order_amount;

CREATE UNIQUE INDEX ON tmp_mpf_order_fee (sales_order_id);
ANALYZE tmp_mpf_order_fee;

SELECT
    order_fees.source_system,
    DATE_TRUNC('month', order_fees.order_date)::date AS order_month,
    order_fees.store_id,
    stores.store_name,
    COUNT(*) AS eligible_orders,
    COUNT(*) FILTER (WHERE order_fees.fee_rows > 0) AS orders_with_fee,
    COUNT(*) FILTER (WHERE order_fees.fee_rows = 0) AS orders_with_unknown_fee,
    SUM(order_fees.net_order_amount) AS recognized_revenue,
    SUM(order_fees.deduction_amount) AS deduction_amount,
    SUM(order_fees.addition_amount) AS addition_amount,
    ROUND(
        100.0 * SUM(order_fees.deduction_amount)
        / NULLIF(SUM(order_fees.net_order_amount), 0),
        2
    ) AS deduction_to_revenue_pct
FROM tmp_mpf_order_fee order_fees
LEFT JOIN public.dim_store stores
    ON stores.store_id = order_fees.store_id
GROUP BY
    order_fees.source_system,
    DATE_TRUNC('month', order_fees.order_date)::date,
    order_fees.store_id,
    stores.store_name
ORDER BY
    order_fees.source_system,
    order_month,
    order_fees.store_id;

\copy (SELECT order_fees.source_system, DATE_TRUNC('month', order_fees.order_date)::date AS order_month, order_fees.store_id, stores.store_name, COUNT(*) AS eligible_orders, COUNT(*) FILTER (WHERE order_fees.fee_rows > 0) AS orders_with_fee, COUNT(*) FILTER (WHERE order_fees.fee_rows = 0) AS orders_with_unknown_fee, SUM(order_fees.net_order_amount) AS recognized_revenue, SUM(order_fees.deduction_amount) AS deduction_amount, SUM(order_fees.addition_amount) AS addition_amount, ROUND(100.0 * SUM(order_fees.deduction_amount) / NULLIF(SUM(order_fees.net_order_amount), 0), 2) AS deduction_to_revenue_pct FROM tmp_mpf_order_fee order_fees LEFT JOIN public.dim_store stores ON stores.store_id = order_fees.store_id GROUP BY order_fees.source_system, DATE_TRUNC('month', order_fees.order_date)::date, order_fees.store_id, stores.store_name ORDER BY order_fees.source_system, order_month, order_fees.store_id) TO '/tmp/sales_marketplace_fee_monthly_store_audit.csv' WITH (FORMAT CSV, HEADER TRUE)

-- G. Order-level outliers where deductions exceed recognized revenue.
SELECT
    source_system,
    COUNT(*) FILTER (
        WHERE COALESCE(deduction_amount, 0) > net_order_amount
    ) AS orders_deduction_above_revenue,
    SUM(net_order_amount) FILTER (
        WHERE COALESCE(deduction_amount, 0) > net_order_amount
    ) AS affected_revenue,
    SUM(deduction_amount) FILTER (
        WHERE COALESCE(deduction_amount, 0) > net_order_amount
    ) AS affected_deduction_amount
FROM tmp_mpf_order_fee
GROUP BY source_system
ORDER BY source_system;

\copy (SELECT * FROM tmp_mpf_order_fee WHERE COALESCE(deduction_amount, 0) > net_order_amount ORDER BY source_system, deduction_amount - net_order_amount DESC, sales_order_id) TO '/tmp/sales_marketplace_fee_order_outliers.csv' WITH (FORMAT CSV, HEADER TRUE)

ROLLBACK;
