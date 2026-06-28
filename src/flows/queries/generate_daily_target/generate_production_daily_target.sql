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
)
INSERT INTO public.fact_production_daily_target (
    target_date,
    target_cycle_start,
    target_cycle_end,
    product_id,
    weekly_need_pcs,
    target_qty_pcs,
    generated_at
)
SELECT
    wd.target_date,
    c.target_cycle_start,
    c.target_cycle_end,
    pp.product_id,
    pp.weekly_need AS weekly_need_pcs,
    CEIL((pp.weekly_need / 6.0) + 10)::int AS target_qty_pcs,
    now() AS generated_at
FROM public.mv_production_planning pp
CROSS JOIN cycle c
CROSS JOIN working_days wd
ON CONFLICT (target_date, product_id)
DO UPDATE SET
    target_cycle_start = EXCLUDED.target_cycle_start,
    target_cycle_end = EXCLUDED.target_cycle_end,
    weekly_need_pcs = EXCLUDED.weekly_need_pcs,
    target_qty_pcs = EXCLUDED.target_qty_pcs,
    generated_at = EXCLUDED.generated_at
WHERE :overwrite_targets;
