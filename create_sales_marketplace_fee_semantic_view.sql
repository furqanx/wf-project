-- Coverage-aware marketplace-fee semantic layer.
-- Marketplace cost uses a positive-cost convention; reversals are negative.

BEGIN;

CREATE OR REPLACE VIEW public.vw_sales_marketplace_fee_semantic AS
SELECT
    fee.sales_settlement_fee_detail_id,
    fee.source_system,
    fee.marketplace_id,
    fee.store_id,
    fee.sales_order_id,
    fee.sales_settlement_id,
    fee.external_order_id,
    fee.external_order_item_id,
    fee.source_sku_code,
    fee.fee_type_id,
    types.fee_code,
    types.fee_name,
    types.fee_category,
    types.economic_role,
    types.include_in_marketplace_cost,
    types.marketplace_cost_behavior,
    fee.raw_fee_name,
    fee.raw_fee_amount,
    fee.signed_fee_amount,
    CASE types.marketplace_cost_behavior
        WHEN 'charge' THEN ABS(fee.signed_fee_amount)
        WHEN 'reversal' THEN -ABS(fee.signed_fee_amount)
        ELSE NULL
    END AS marketplace_cost_amount,
    fee.fee_grain_type,
    fee.source_file,
    fee.source_sheet,
    fee.source_row_number,
    fee.raw_record_id,
    fee.created_at,
    fee.updated_at
FROM public.fact_sales_settlement_fee_detail fee
JOIN public.fee_type types
  ON types.fee_type_id = fee.fee_type_id
WHERE fee.is_active
  AND types.is_active;

COMMENT ON VIEW public.vw_sales_marketplace_fee_semantic IS
'Governed fee-detail semantics. marketplace_cost_amount is populated only for approved seller-cost charges and reversals; NULL means excluded or unclassified, not zero.';

COMMIT;

