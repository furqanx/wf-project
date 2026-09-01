-- Performance indexes for sales phase 3 fee detail transform.
-- Safe to rerun.

CREATE INDEX IF NOT EXISTS idx_fact_sales_settlement_phase3_lookup
ON public.fact_sales_settlement (
    source_system,
    sales_channel_type,
    store_id,
    external_order_id,
    COALESCE(external_order_item_id, ''),
    COALESCE(source_sku_code, '')
);

CREATE INDEX IF NOT EXISTS idx_fact_sales_settlement_fee_detail_phase3_source
ON public.fact_sales_settlement_fee_detail (
    source_system,
    store_id,
    external_order_id
);

ANALYZE public.fact_sales_settlement;
ANALYZE public.fact_sales_settlement_fee_detail;
