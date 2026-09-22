-- Resolve overlapping marketplace-fee exports without deleting raw facts.
-- Safe to rerun after govern_sales_marketplace_fee_semantics.sql.

BEGIN;

-- The prorated Shopee processing fee is an allocation of the order-level fee,
-- not an additional marketplace cost.
ALTER TABLE public.fee_type
DROP CONSTRAINT IF EXISTS ck_fee_type_economic_role;

ALTER TABLE public.fee_type
ADD CONSTRAINT ck_fee_type_economic_role CHECK (economic_role IN (
    'platform_fee',
    'seller_funded_discount',
    'platform_funded_benefit',
    'logistics_pass_through',
    'cost_reversal',
    'cost_allocation',
    'settlement_adjustment',
    'revenue_component',
    'aggregate_total',
    'unclassified'
));

UPDATE public.fee_type
SET
    economic_role = 'cost_allocation',
    include_in_marketplace_cost = false,
    marketplace_cost_behavior = 'not_applicable',
    updated_at = now()
WHERE source_system = 'shopee'
  AND fee_code = 'biaya_proses_pesanan_per_produk_prorata';

CREATE OR REPLACE VIEW public.vw_sales_marketplace_fee_semantic AS
WITH base AS (
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
      AND types.is_active
),
source_priority AS (
    SELECT
        base.*,
        DENSE_RANK() OVER (
            PARTITION BY
                source_system,
                store_id,
                external_order_id,
                fee_type_id,
                COALESCE(external_order_item_id, ''),
                COALESCE(source_sku_code, '')
            ORDER BY source_file DESC NULLS LAST
        ) AS source_file_priority
    FROM base
),
selected AS (
    SELECT
        source_priority.*,
        CASE
            WHEN NOT include_in_marketplace_cost THEN false
            WHEN source_system = 'shopee'
             AND fee_code = 'biaya_proses_pesanan'
             AND (source_sheet <> 'Income' OR fee_grain_type <> 'order_level')
                THEN false
            WHEN source_file_priority <> 1 THEN false
            ELSE true
        END AS is_marketplace_cost_selected,
        CASE
            WHEN NOT include_in_marketplace_cost THEN economic_role
            WHEN source_system = 'shopee'
             AND fee_code = 'biaya_proses_pesanan'
             AND (source_sheet <> 'Income' OR fee_grain_type <> 'order_level')
                THEN 'duplicate_item_representation'
            WHEN source_file_priority <> 1 THEN 'overlapping_source_file'
            ELSE NULL
        END AS marketplace_cost_exclusion_reason
    FROM source_priority
)
SELECT
    sales_settlement_fee_detail_id,
    source_system,
    marketplace_id,
    store_id,
    sales_order_id,
    sales_settlement_id,
    external_order_id,
    external_order_item_id,
    source_sku_code,
    fee_type_id,
    fee_code,
    fee_name,
    fee_category,
    economic_role,
    include_in_marketplace_cost,
    marketplace_cost_behavior,
    raw_fee_name,
    raw_fee_amount,
    signed_fee_amount,
    CASE
        WHEN NOT is_marketplace_cost_selected THEN NULL
        WHEN marketplace_cost_behavior = 'charge' THEN ABS(signed_fee_amount)
        WHEN marketplace_cost_behavior = 'reversal' THEN -ABS(signed_fee_amount)
        ELSE NULL
    END AS marketplace_cost_amount,
    fee_grain_type,
    source_file,
    source_sheet,
    source_row_number,
    raw_record_id,
    created_at,
    updated_at,
    is_marketplace_cost_selected,
    marketplace_cost_exclusion_reason
FROM selected;

COMMENT ON VIEW public.vw_sales_marketplace_fee_semantic IS
'Governed fee semantics with source-overlap resolution. Marketplace cost uses one preferred source export; excluded raw rows remain visible with a reason.';

COMMIT;
