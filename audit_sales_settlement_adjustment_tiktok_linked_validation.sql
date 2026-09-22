-- Validate the 39 linked TikTok/Tokopedia adjustments and isolate the four
-- genuine non-order commission adjustments from marketing spend.

\pset pager off
SET lock_timeout = '30s';
SET statement_timeout = '30min';

-- A. Linked-row identity and relationship consistency by transaction type.
WITH linked AS (
    SELECT
        adjustment.*,
        settlement.sales_order_id AS settlement_sales_order_id,
        settlement.external_order_id AS settlement_external_order_id,
        settlement.store_id AS settlement_store_id,
        orders.external_order_id AS order_external_order_id,
        orders.store_id AS order_store_id
    FROM public.fact_sales_settlement_adjustment adjustment
    LEFT JOIN public.fact_sales_settlement settlement
      ON settlement.sales_settlement_id = adjustment.sales_settlement_id
    LEFT JOIN public.fact_sales_order orders
      ON orders.sales_order_id = adjustment.sales_order_id
    WHERE adjustment.is_active = TRUE
      AND adjustment.source_system = 'tiktok_tokopedia'
      AND (
          adjustment.sales_order_id IS NOT NULL
          OR adjustment.sales_settlement_id IS NOT NULL
      )
)
SELECT
    raw_transaction_type,
    COUNT(*) AS adjustment_rows,
    COUNT(DISTINCT external_adjustment_id) AS external_adjustment_ids,
    COUNT(DISTINCT related_external_order_id) AS related_order_ids,
    COUNT(*) FILTER (
        WHERE sales_order_id IS NOT NULL
    ) AS linked_order_rows,
    COUNT(*) FILTER (
        WHERE sales_settlement_id IS NOT NULL
    ) AS linked_settlement_rows,
    COUNT(*) FILTER (
        WHERE sales_order_id IS NOT NULL
          AND related_external_order_id = order_external_order_id
    ) AS related_id_matches_order_rows,
    COUNT(*) FILTER (
        WHERE sales_settlement_id IS NOT NULL
          AND related_external_order_id = settlement_external_order_id
    ) AS related_id_matches_settlement_rows,
    COUNT(*) FILTER (
        WHERE sales_order_id IS NOT NULL
          AND order_store_id IS DISTINCT FROM store_id
    ) AS cross_store_order_rows,
    COUNT(*) FILTER (
        WHERE sales_settlement_id IS NOT NULL
          AND settlement_store_id IS DISTINCT FROM store_id
    ) AS cross_store_settlement_rows,
    COUNT(*) FILTER (
        WHERE sales_order_id IS NOT NULL
          AND settlement_sales_order_id IS NOT NULL
          AND sales_order_id <> settlement_sales_order_id
    ) AS order_settlement_mismatch_rows,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount
FROM linked
GROUP BY raw_transaction_type
ORDER BY adjustment_rows DESC, raw_transaction_type;

-- B. Full evidence for repeated external adjustment IDs. Repetition may be
-- legitimate when one adjustment event references multiple distinct orders.
SELECT
    adjustment.sales_settlement_adjustment_id,
    adjustment.store_id,
    adjustment.external_adjustment_id,
    adjustment.related_external_order_id,
    adjustment.raw_transaction_type,
    adjustment.signed_adjustment_amount,
    adjustment.sales_order_id,
    adjustment.sales_settlement_id,
    adjustment.adjustment_occurred_at,
    adjustment.source_file,
    adjustment.source_row_number,
    adjustment.raw_record_id
FROM public.fact_sales_settlement_adjustment adjustment
JOIN (
    SELECT store_id, external_adjustment_id
    FROM public.fact_sales_settlement_adjustment
    WHERE is_active = TRUE
      AND source_system = 'tiktok_tokopedia'
    GROUP BY store_id, external_adjustment_id
    HAVING COUNT(*) > 1
) repeated
  ON repeated.store_id = adjustment.store_id
 AND repeated.external_adjustment_id = adjustment.external_adjustment_id
WHERE adjustment.is_active = TRUE
  AND adjustment.source_system = 'tiktok_tokopedia'
ORDER BY
    adjustment.store_id,
    adjustment.external_adjustment_id,
    adjustment.sales_settlement_adjustment_id;

-- C. The four unlinked non-marketing adjustments.
SELECT
    sales_settlement_adjustment_id,
    store_id,
    external_adjustment_id,
    related_external_order_id,
    raw_transaction_type,
    signed_adjustment_amount,
    adjustment_occurred_at,
    source_file,
    source_row_number,
    raw_record_id
FROM public.fact_sales_settlement_adjustment
WHERE is_active = TRUE
  AND source_system = 'tiktok_tokopedia'
  AND sales_order_id IS NULL
  AND sales_settlement_id IS NULL
  AND LOWER(COALESCE(raw_transaction_type, '')) NOT LIKE
      '%gmv payment for tiktok ads%'
  AND LOWER(COALESCE(raw_transaction_type, '')) NOT LIKE
      '%pembayaran gmv untuk iklan tiktok%'
  AND LOWER(COALESCE(raw_transaction_type, '')) NOT LIKE
      '%campaign package%'
  AND LOWER(COALESCE(raw_transaction_type, '')) NOT LIKE
      '%gmv payment for promote%'
ORDER BY adjustment_occurred_at, sales_settlement_adjustment_id;

-- D. Revised classification totals.
SELECT
    CASE
        WHEN LOWER(COALESCE(raw_transaction_type, '')) LIKE
             '%gmv payment for tiktok ads%'
          OR LOWER(COALESCE(raw_transaction_type, '')) LIKE
             '%pembayaran gmv untuk iklan tiktok%'
          OR LOWER(COALESCE(raw_transaction_type, '')) LIKE
             '%gmv payment for promote%'
            THEN 'ads_cost'
        WHEN LOWER(COALESCE(raw_transaction_type, '')) LIKE
             '%campaign package%'
            THEN 'campaign_marketing_cost'
        WHEN sales_order_id IS NOT NULL
          OR sales_settlement_id IS NOT NULL
            THEN 'order_settlement_adjustment'
        ELSE 'store_period_settlement_adjustment'
    END AS governed_category,
    COUNT(*) AS adjustment_rows,
    SUM(signed_adjustment_amount) AS signed_adjustment_amount,
    COUNT(*) FILTER (WHERE store_id IS NULL) AS rows_without_store,
    COUNT(*) FILTER (
        WHERE adjustment_occurred_at IS NULL
    ) AS rows_without_business_date
FROM public.fact_sales_settlement_adjustment
WHERE is_active = TRUE
  AND source_system = 'tiktok_tokopedia'
GROUP BY 1
ORDER BY adjustment_rows DESC, governed_category;
