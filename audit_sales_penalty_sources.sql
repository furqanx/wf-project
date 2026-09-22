-- Audit marketplace penalty sources and potential cross-fact double counting.
-- Read-only: no production facts are updated.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

BEGIN;

CREATE TEMP TABLE tmp_sales_penalty_candidate ON COMMIT DROP AS
WITH balance_candidate AS (
    SELECT
        balance.source_system,
        balance.marketplace_id,
        balance.store_id,
        'balance_transaction'::text AS source_fact,
        balance.balance_transaction_id::text AS source_record_id,
        balance.external_transaction_id AS external_reference_id,
        balance.sales_order_id,
        balance.sales_settlement_id,
        balance.transaction_occurred_at AS event_at,
        balance.transaction_type AS raw_type,
        balance.transaction_sub_type AS raw_sub_type,
        balance.transaction_description AS raw_description,
        balance.movement_direction,
        balance.signed_amount,
        NULL::text AS sign_confidence,
        NULL::text AS fee_code,
        NULL::text AS fee_category,
        NULL::boolean AS included_in_marketplace_cost,
        balance.source_file,
        balance.source_sheet,
        balance.source_row_number,
        balance.raw_record_id
    FROM public.fact_balance_transaction balance
    WHERE balance.is_active = TRUE
      AND CONCAT_WS(
              ' ',
              balance.transaction_type,
              balance.transaction_sub_type,
              balance.transaction_description,
              balance.transaction_description_key
          ) ~* '(penalt|denda|violation|(^|[^a-z])fine([^a-z]|$))'
),
adjustment_candidate AS (
    SELECT
        adjustment.source_system,
        adjustment.marketplace_id,
        adjustment.store_id,
        'settlement_adjustment'::text AS source_fact,
        adjustment.sales_settlement_adjustment_id::text AS source_record_id,
        adjustment.external_adjustment_id AS external_reference_id,
        adjustment.sales_order_id,
        adjustment.sales_settlement_id,
        adjustment.adjustment_occurred_at AS event_at,
        adjustment.raw_transaction_type AS raw_type,
        adjustment.adjustment_scope AS raw_sub_type,
        adjustment.raw_adjustment_name AS raw_description,
        CASE
            WHEN adjustment.signed_adjustment_amount < 0 THEN 'debit'
            WHEN adjustment.signed_adjustment_amount > 0 THEN 'credit'
            ELSE 'zero'
        END AS movement_direction,
        adjustment.signed_adjustment_amount AS signed_amount,
        adjustment.sign_confidence,
        fee.fee_code,
        fee.fee_category,
        fee.include_in_marketplace_cost AS included_in_marketplace_cost,
        adjustment.source_file,
        adjustment.source_sheet,
        adjustment.source_row_number,
        adjustment.raw_record_id
    FROM public.fact_sales_settlement_adjustment adjustment
    JOIN public.fee_type fee
      ON fee.fee_type_id = adjustment.fee_type_id
    WHERE adjustment.is_active = TRUE
      AND CONCAT_WS(
              ' ',
              adjustment.raw_transaction_type,
              adjustment.raw_adjustment_name,
              fee.fee_code,
              fee.fee_name,
              fee.fee_category
          ) ~* '(penalt|denda|violation|(^|[^a-z])fine([^a-z]|$))'
),
fee_candidate AS (
    SELECT
        detail.source_system,
        detail.marketplace_id,
        detail.store_id,
        'settlement_fee_detail'::text AS source_fact,
        detail.sales_settlement_fee_detail_id::text AS source_record_id,
        detail.external_order_id AS external_reference_id,
        detail.sales_order_id,
        detail.sales_settlement_id,
        COALESCE(
            settlement.settled_at,
            settlement.released_at,
            settlement.order_created_at
        ) AS event_at,
        detail.raw_fee_name AS raw_type,
        detail.fee_grain_type AS raw_sub_type,
        fee.fee_name AS raw_description,
        CASE
            WHEN detail.signed_fee_amount < 0 THEN 'debit'
            WHEN detail.signed_fee_amount > 0 THEN 'credit'
            ELSE 'zero'
        END AS movement_direction,
        detail.signed_fee_amount AS signed_amount,
        detail.sign_confidence,
        fee.fee_code,
        fee.fee_category,
        fee.include_in_marketplace_cost AS included_in_marketplace_cost,
        detail.source_file,
        detail.source_sheet,
        detail.source_row_number,
        detail.raw_record_id
    FROM public.fact_sales_settlement_fee_detail detail
    JOIN public.fee_type fee
      ON fee.fee_type_id = detail.fee_type_id
    LEFT JOIN public.fact_sales_settlement settlement
      ON settlement.sales_settlement_id = detail.sales_settlement_id
    WHERE detail.is_active = TRUE
      AND CONCAT_WS(
              ' ',
              detail.raw_fee_name,
              fee.fee_code,
              fee.fee_name,
              fee.fee_category
          ) ~* '(penalt|denda|violation|(^|[^a-z])fine([^a-z]|$))'
)
SELECT * FROM balance_candidate
UNION ALL
SELECT * FROM adjustment_candidate
UNION ALL
SELECT * FROM fee_candidate;

CREATE INDEX ON tmp_sales_penalty_candidate (
    source_system,
    source_fact,
    store_id,
    event_at
);
CREATE INDEX ON tmp_sales_penalty_candidate (raw_record_id);
ANALYZE tmp_sales_penalty_candidate;

-- A. Candidate inventory and source semantics.
SELECT
    source_system,
    source_fact,
    raw_type,
    raw_sub_type,
    raw_description,
    movement_direction,
    sign_confidence,
    fee_code,
    fee_category,
    included_in_marketplace_cost,
    COUNT(*) AS penalty_rows,
    COUNT(DISTINCT store_id) AS stores,
    COUNT(*) FILTER (WHERE sales_order_id IS NOT NULL) AS linked_order_rows,
    COUNT(*) FILTER (
        WHERE sales_settlement_id IS NOT NULL
    ) AS linked_settlement_rows,
    SUM(signed_amount) AS signed_amount,
    SUM(-signed_amount) FILTER (WHERE signed_amount < 0)
        AS candidate_penalty_cost,
    SUM(signed_amount) FILTER (WHERE signed_amount > 0)
        AS candidate_penalty_reversal,
    MIN(event_at) AS min_event_at,
    MAX(event_at) AS max_event_at
FROM tmp_sales_penalty_candidate
GROUP BY
    source_system,
    source_fact,
    raw_type,
    raw_sub_type,
    raw_description,
    movement_direction,
    sign_confidence,
    fee_code,
    fee_category,
    included_in_marketplace_cost
ORDER BY source_system, source_fact, penalty_rows DESC;

-- B. Compact row detail for semantic review.
SELECT
    source_system,
    source_fact,
    source_record_id,
    store_id,
    event_at,
    external_reference_id,
    sales_order_id,
    sales_settlement_id,
    raw_type,
    raw_sub_type,
    raw_description,
    movement_direction,
    signed_amount,
    sign_confidence,
    fee_code,
    fee_category,
    included_in_marketplace_cost,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id
FROM tmp_sales_penalty_candidate
ORDER BY source_system, source_fact, event_at, source_record_id
LIMIT 250;

-- C. Coverage by source, store, and month.
SELECT
    source_system,
    source_fact,
    DATE_TRUNC('month', event_at)::date AS event_month,
    store_id,
    COUNT(*) AS penalty_rows,
    SUM(signed_amount) AS signed_amount,
    SUM(-signed_amount) FILTER (WHERE signed_amount < 0)
        AS candidate_penalty_cost,
    SUM(signed_amount) FILTER (WHERE signed_amount > 0)
        AS candidate_penalty_reversal
FROM tmp_sales_penalty_candidate
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, 3, 4;

-- D. The same raw record represented in more than one fact is a possible
-- double-counting boundary and requires explicit source precedence.
SELECT
    source_system,
    raw_record_id,
    COUNT(*) AS represented_rows,
    COUNT(DISTINCT source_fact) AS source_facts,
    STRING_AGG(DISTINCT source_fact, ' | ' ORDER BY source_fact)
        AS source_fact_list,
    SUM(signed_amount) AS summed_signed_amount
FROM tmp_sales_penalty_candidate
GROUP BY source_system, raw_record_id
HAVING COUNT(DISTINCT source_fact) > 1
ORDER BY source_facts DESC, source_system, raw_record_id;

-- E. A source-file/row match catches cross-fact copies even when each loader
-- generated a different raw_record_id.
SELECT
    source_system,
    source_file,
    source_sheet,
    source_row_number,
    COUNT(*) AS represented_rows,
    COUNT(DISTINCT source_fact) AS source_facts,
    STRING_AGG(DISTINCT source_fact, ' | ' ORDER BY source_fact)
        AS source_fact_list,
    SUM(signed_amount) AS summed_signed_amount
FROM tmp_sales_penalty_candidate
WHERE source_file IS NOT NULL
  AND source_row_number IS NOT NULL
GROUP BY
    source_system,
    source_file,
    source_sheet,
    source_row_number
HAVING COUNT(DISTINCT source_fact) > 1
ORDER BY source_facts DESC, source_system, source_file, source_row_number;

-- F. Repeated identities within one source fact.
SELECT
    source_system,
    source_fact,
    store_id,
    external_reference_id,
    COUNT(*) AS penalty_rows,
    COUNT(DISTINCT signed_amount) AS distinct_amounts,
    COUNT(DISTINCT source_file) AS source_files,
    SUM(signed_amount) AS signed_amount
FROM tmp_sales_penalty_candidate
WHERE external_reference_id IS NOT NULL
GROUP BY
    source_system,
    source_fact,
    store_id,
    external_reference_id
HAVING COUNT(*) > 1
ORDER BY penalty_rows DESC, source_system, source_fact;

-- G. Readiness indicators. These are diagnostic, not all expected to be zero:
-- marketplace-cost rows reveal double-counting risk; low confidence requires
-- sign review; credit rows may be valid penalty reversals.
SELECT
    COUNT(*) AS candidate_rows,
    COUNT(*) FILTER (WHERE store_id IS NULL) AS rows_without_store,
    COUNT(*) FILTER (WHERE event_at IS NULL) AS rows_without_event_time,
    COUNT(*) FILTER (WHERE signed_amount = 0) AS zero_amount_rows,
    COUNT(*) FILTER (
        WHERE sign_confidence = 'low'
    ) AS low_confidence_rows,
    COUNT(*) FILTER (
        WHERE included_in_marketplace_cost = TRUE
    ) AS already_in_marketplace_cost_rows,
    COUNT(*) FILTER (
        WHERE movement_direction = 'credit'
    ) AS possible_reversal_rows
FROM tmp_sales_penalty_candidate;

ROLLBACK;
