-- Performance indexes for sales phase 1 transforms.
-- Safe to rerun.

CREATE INDEX IF NOT EXISTS idx_fact_sales_order_source_channel_store_order
ON public.fact_sales_order (
    source_system,
    sales_channel_type,
    store_id,
    external_order_id
);

CREATE INDEX IF NOT EXISTS idx_fact_sales_order_item_order_line
ON public.fact_sales_order_item (
    sales_order_id,
    source_line_id
);

CREATE INDEX IF NOT EXISTS idx_fact_sales_order_addon_order_line
ON public.fact_sales_order_addon (
    sales_order_id,
    source_line_id
);

ANALYZE public.fact_sales_order;
ANALYZE public.fact_sales_order_item;
ANALYZE public.fact_sales_order_addon;
