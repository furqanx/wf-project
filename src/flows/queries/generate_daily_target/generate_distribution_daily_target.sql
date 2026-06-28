WITH params AS (
    SELECT COALESCE(CAST(:reference_date AS date), CURRENT_DATE) AS run_date
),
cycle AS (
    SELECT
        CASE
            WHEN EXTRACT(day FROM run_date)::int <= 20
                THEN (date_trunc('month', run_date)::date - INTERVAL '1 month' + INTERVAL '20 days')::date
            ELSE (date_trunc('month', run_date)::date + INTERVAL '20 days')::date
        END AS target_cycle_start,
        CASE
            WHEN EXTRACT(day FROM run_date)::int <= 20
                THEN (date_trunc('month', run_date)::date + INTERVAL '19 days')::date
            ELSE (date_trunc('month', run_date)::date + INTERVAL '1 month' + INTERVAL '19 days')::date
        END AS target_cycle_end
    FROM params
),
working_days AS (
    SELECT gs::date AS target_date
    FROM cycle c
    CROSS JOIN generate_series(c.target_cycle_start, c.target_cycle_end, INTERVAL '1 day') AS gs
    WHERE EXTRACT(isodow FROM gs) BETWEEN 1 AND 6
),
distribution_planning AS (
    SELECT
        dp.target_date,
        c.target_cycle_start,
        c.target_cycle_end,
        mdp.warehouse_id,
        mdp.sales_channel_id,
        mdp.product_id,
        mdp.weekly_need AS weekly_need_pcs,
        CEIL((mdp.weekly_need / 6.0) + 10)::int AS target_qty_pcs
    FROM public.mv_distribution_planning mdp
    CROSS JOIN cycle c
    CROSS JOIN working_days dp
    WHERE mdp.warehouse_id IS NOT NULL
        AND mdp.sales_channel_id IS NOT NULL
        AND mdp.product_id IS NOT NULL
)
INSERT INTO public.fact_distribution_daily_target (
    target_date,
    target_cycle_start,
    target_cycle_end,
    warehouse_id,
    sales_channel_id,
    product_id,
    weekly_need_pcs,
    target_qty_pcs,
    generated_at
)
    SELECT
        target_date,
        target_cycle_start,
        target_cycle_end,
        warehouse_id,
        sales_channel_id,
        product_id,
        weekly_need_pcs,
        target_qty_pcs,
        now() AS generated_at
    FROM distribution_planning
ON CONFLICT (target_date, warehouse_id, sales_channel_id, product_id)
    DO UPDATE SET
        target_cycle_start = EXCLUDED.target_cycle_start,
        target_cycle_end = EXCLUDED.target_cycle_end,
        weekly_need_pcs = EXCLUDED.weekly_need_pcs,
        target_qty_pcs = EXCLUDED.target_qty_pcs,
        generated_at = EXCLUDED.generated_at
    WHERE :overwrite_targets;
