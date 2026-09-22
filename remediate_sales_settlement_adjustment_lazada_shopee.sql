-- Finalize safe Lazada/Shopee settlement-adjustment attribution decisions.
-- Only propagate an order already established by the linked settlement.

BEGIN;

WITH safe_settlement_order AS (
    SELECT
        adjustment.sales_settlement_adjustment_id,
        settlement.sales_order_id
    FROM public.fact_sales_settlement_adjustment adjustment
    JOIN public.fact_sales_settlement settlement
      ON settlement.sales_settlement_id = adjustment.sales_settlement_id
     AND settlement.is_active = TRUE
    WHERE adjustment.is_active = TRUE
      AND adjustment.source_system = 'shopee'
      AND adjustment.sales_order_id IS NULL
      AND settlement.sales_order_id IS NOT NULL
      AND adjustment.store_id = settlement.store_id
      AND NULLIF(BTRIM(adjustment.related_external_order_id), '') =
          settlement.external_order_id
)
UPDATE public.fact_sales_settlement_adjustment adjustment
SET
    sales_order_id = safe.sales_order_id,
    adjustment_scope = 'settlement_related',
    notes = CASE
        WHEN COALESCE(adjustment.notes, '') LIKE
             '%Governed order linkage inherited from settlement%'
            THEN adjustment.notes
        ELSE CONCAT_WS(
            '; ',
            adjustment.notes,
            'Governed order linkage inherited from settlement'
        )
    END,
    updated_at = NOW()
FROM safe_settlement_order safe
WHERE safe.sales_settlement_adjustment_id =
      adjustment.sales_settlement_adjustment_id;

COMMIT;
