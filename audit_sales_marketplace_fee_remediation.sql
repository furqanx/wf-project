-- Validate governed Marketplace Cost semantics before publication.
-- Run after govern_sales_marketplace_fee_semantics.sql and
-- create_sales_marketplace_fee_semantic_view.sql.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_marketplace_fee_semantic ON COMMIT DROP AS
SELECT *
FROM public.vw_sales_marketplace_fee_semantic;

CREATE INDEX ON tmp_marketplace_fee_semantic (source_system, economic_role);
CREATE INDEX ON tmp_marketplace_fee_semantic (source_system, store_id, external_order_id, fee_type_id);
ANALYZE tmp_marketplace_fee_semantic;

-- A. Observed fee rows that still lack an economic classification.
SELECT
    semantic.source_system,
    semantic.fee_type_id,
    semantic.fee_code,
    semantic.fee_name,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT semantic.external_order_id) AS orders,
    SUM(semantic.signed_fee_amount) AS signed_amount
FROM tmp_marketplace_fee_semantic semantic
WHERE semantic.economic_role = 'unclassified'
GROUP BY 1, 2, 3, 4
ORDER BY 1, ABS(SUM(semantic.signed_fee_amount)) DESC, 2;

\copy (SELECT source_system, fee_type_id, fee_code, fee_name, COUNT(*) AS fee_rows, COUNT(DISTINCT external_order_id) AS orders, SUM(signed_fee_amount) AS signed_amount FROM tmp_marketplace_fee_semantic WHERE economic_role = 'unclassified' GROUP BY 1, 2, 3, 4 ORDER BY 1, ABS(SUM(signed_fee_amount)) DESC, 2) TO '/tmp/sales_marketplace_fee_unclassified.csv' WITH (FORMAT CSV, HEADER TRUE)

-- B. Official Marketplace Cost candidate by source and economic role.
SELECT
    source_system,
    economic_role,
    marketplace_cost_behavior,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT external_order_id) AS orders,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM tmp_marketplace_fee_semantic
WHERE include_in_marketplace_cost
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

-- C. Components excluded from Marketplace Cost remain visible and auditable.
SELECT
    source_system,
    economic_role,
    COUNT(*) AS fee_rows,
    COUNT(DISTINCT external_order_id) AS orders,
    SUM(signed_fee_amount) AS signed_amount
FROM tmp_marketplace_fee_semantic
WHERE NOT include_in_marketplace_cost
GROUP BY 1, 2
ORDER BY 1, 2;

-- D. Source-file overlap by order and fee type. More than one source file name
-- for the same component is a duplication candidate, not automatic proof.
WITH component_source AS (
    SELECT
        source_system,
        store_id,
        external_order_id,
        fee_type_id,
        fee_code,
        COUNT(DISTINCT source_file) AS source_file_count,
        COUNT(*) AS fee_rows,
        SUM(marketplace_cost_amount) AS marketplace_cost_amount
    FROM tmp_marketplace_fee_semantic
    WHERE include_in_marketplace_cost
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    source_system,
    fee_type_id,
    fee_code,
    COUNT(*) AS affected_order_components,
    SUM(fee_rows) AS fee_rows,
    SUM(marketplace_cost_amount) AS marketplace_cost_amount
FROM component_source
WHERE source_file_count > 1
GROUP BY 1, 2, 3
ORDER BY 1, marketplace_cost_amount DESC NULLS LAST, 2;

\copy (WITH component_source AS (SELECT source_system, store_id, external_order_id, fee_type_id, fee_code, COUNT(DISTINCT source_file) AS source_file_count, COUNT(*) AS fee_rows, SUM(marketplace_cost_amount) AS marketplace_cost_amount FROM tmp_marketplace_fee_semantic WHERE include_in_marketplace_cost GROUP BY 1, 2, 3, 4, 5) SELECT source_system, fee_type_id, fee_code, COUNT(*) AS affected_order_components, SUM(fee_rows) AS fee_rows, SUM(marketplace_cost_amount) AS marketplace_cost_amount FROM component_source WHERE source_file_count > 1 GROUP BY 1, 2, 3 ORDER BY 1, marketplace_cost_amount DESC NULLS LAST, 2) TO '/tmp/sales_marketplace_fee_source_overlap.csv' WITH (FORMAT CSV, HEADER TRUE)

-- E. Sanity guardrails. All counts must be zero before KPI publication.
SELECT
    COUNT(*) FILTER (
        WHERE include_in_marketplace_cost
          AND economic_role NOT IN ('platform_fee', 'cost_reversal')
    ) AS invalid_included_role_rows,
    COUNT(*) FILTER (
        WHERE include_in_marketplace_cost
          AND marketplace_cost_amount IS NULL
    ) AS included_without_cost_amount_rows,
    COUNT(*) FILTER (
        WHERE economic_role = 'unclassified'
    ) AS unclassified_observed_rows
FROM tmp_marketplace_fee_semantic;

ROLLBACK;
