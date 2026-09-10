-- Product master patch for legacy production target rows.
-- Safe to rerun.

BEGIN;

WITH seed (product_name, product_category, product_type, base_unit, net_weight_value, net_weight_unit) AS (
VALUES
    ('Beras Amazinc 25 KG', 'Beras', 'finished_good', 'PCS', 25, 'KG'),
    ('Beras Diet 25 KG', 'Beras', 'finished_good', 'PCS', 25, 'KG')
)
INSERT INTO public.dim_product (
    product_name,
    product_category,
    product_type,
    base_unit,
    net_weight_value,
    net_weight_unit
)
SELECT
    product_name,
    product_category,
    product_type,
    base_unit,
    net_weight_value,
    net_weight_unit
FROM seed
ON CONFLICT (product_name) DO UPDATE SET
    product_category = EXCLUDED.product_category,
    product_type = EXCLUDED.product_type,
    base_unit = EXCLUDED.base_unit,
    net_weight_value = EXCLUDED.net_weight_value,
    net_weight_unit = EXCLUDED.net_weight_unit,
    is_active = true,
    updated_at = now();

COMMIT;
