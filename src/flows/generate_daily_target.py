import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from prefect import flow, get_run_logger, task
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from src.db_config import get_engine  # noqa: E402


PLANNING_MATERIALIZED_VIEWS = [
    "public.mv_production_planning",
    "public.mv_distribution_planning",
]

DASHBOARD_MATERIALIZED_VIEWS = [
    "public.mv_production_daily_target_vs_realization",
    "public.mv_distribution_daily_target_vs_realization",
]


def _reference_date_sql(reference_date: str | None) -> str:
    if reference_date:
        return "CAST(:reference_date AS date)"
    return "CURRENT_DATE"


@task
def refresh_planning_materialized_views() -> None:
    logger = get_run_logger()
    engine = get_engine()

    with engine.begin() as conn:
        for mv in PLANNING_MATERIALIZED_VIEWS:
            logger.info("Refresh materialized view planning: %s", mv)
            conn.execute(text(f"REFRESH MATERIALIZED VIEW {mv}"))


@task
def generate_production_daily_target(
    reference_date: str | None = None,
    overwrite_targets: bool = False,
) -> int:
    logger = get_run_logger()
    engine = get_engine()
    ref_sql = _reference_date_sql(reference_date)

    query = text(f"""
        WITH params AS (
            SELECT {ref_sql} AS run_date
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
    """)

    params = {
        "reference_date": reference_date,
        "overwrite_targets": overwrite_targets,
    }

    with engine.begin() as conn:
        result = conn.execute(query, params)
        rowcount = result.rowcount or 0

    logger.info(
        "Production daily target generated. affected_rows=%s overwrite_targets=%s reference_date=%s",
        rowcount,
        overwrite_targets,
        reference_date or "CURRENT_DATE",
    )
    return rowcount


@task
def generate_distribution_daily_target(
    reference_date: str | None = None,
    overwrite_targets: bool = False,
) -> int:
    logger = get_run_logger()
    engine = get_engine()
    ref_sql = _reference_date_sql(reference_date)

    query = text(f"""
        WITH params AS (
            SELECT {ref_sql} AS run_date
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
        channel_map AS (
            SELECT
                LOWER(TRIM(w.warehouse_name)) AS warehouse_name_key,
                LOWER(TRIM(sc.channel_name)) AS store_name_key,
                MIN(w.warehouse_id) AS warehouse_id,
                MIN(sc.sales_channel_id) AS sales_channel_id
            FROM public.dim_sales_channel sc
            JOIN public.dim_warehouse w
                ON w.warehouse_id = sc.warehouse_id
            GROUP BY LOWER(TRIM(w.warehouse_name)), LOWER(TRIM(sc.channel_name))
            HAVING COUNT(DISTINCT sc.sales_channel_id) = 1
        ),
        distribution_planning AS (
            SELECT
                dp.target_date,
                c.target_cycle_start,
                c.target_cycle_end,
                cm.warehouse_id,
                cm.sales_channel_id,
                mdp.product_id,
                mdp.weekly_need AS weekly_need_pcs,
                CEIL((mdp.weekly_need / 6.0) + 10)::int AS target_qty_pcs
            FROM public.mv_distribution_planning mdp
            CROSS JOIN cycle c
            CROSS JOIN working_days dp
            JOIN channel_map cm
                ON cm.warehouse_name_key = LOWER(TRIM(mdp.warehouse_name))
               AND cm.store_name_key = LOWER(TRIM(mdp.store_name))
            WHERE mdp.warehouse_name <> 'Offline'
              AND mdp.store_name <> 'Offline'
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
    """)

    params = {
        "reference_date": reference_date,
        "overwrite_targets": overwrite_targets,
    }

    with engine.begin() as conn:
        result = conn.execute(query, params)
        rowcount = result.rowcount or 0

    logger.info(
        "Distribution daily target generated. affected_rows=%s overwrite_targets=%s reference_date=%s",
        rowcount,
        overwrite_targets,
        reference_date or "CURRENT_DATE",
    )
    return rowcount


@task
def validate_distribution_planning_mapping() -> None:
    engine = get_engine()
    query = text("""
        WITH mapping_counts AS (
            SELECT
                LOWER(TRIM(w.warehouse_name)) AS warehouse_name_key,
                LOWER(TRIM(sc.channel_name)) AS store_name_key,
                COUNT(DISTINCT sc.sales_channel_id) AS matching_channels
            FROM public.dim_sales_channel sc
            JOIN public.dim_warehouse w
                ON w.warehouse_id = sc.warehouse_id
            GROUP BY LOWER(TRIM(w.warehouse_name)), LOWER(TRIM(sc.channel_name))
        ),
        planning AS (
            SELECT DISTINCT
                mdp.warehouse_name,
                mdp.store_name,
                LOWER(TRIM(mdp.warehouse_name)) AS warehouse_name_key,
                LOWER(TRIM(mdp.store_name)) AS store_name_key
            FROM public.mv_distribution_planning mdp
            WHERE mdp.warehouse_name <> 'Offline'
              AND mdp.store_name <> 'Offline'
        )
        SELECT
            p.warehouse_name,
            p.store_name,
            COALESCE(mc.matching_channels, 0) AS matching_channels
        FROM planning p
        LEFT JOIN mapping_counts mc
            ON mc.warehouse_name_key = p.warehouse_name_key
           AND mc.store_name_key = p.store_name_key
        WHERE COALESCE(mc.matching_channels, 0) <> 1
        ORDER BY p.warehouse_name, p.store_name;
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()

    if rows:
        details = "; ".join(
            f"{row['warehouse_name']} / {row['store_name']} -> {row['matching_channels']} channel"
            for row in rows
        )
        raise RuntimeError(
            "Mapping mv_distribution_planning ke dim_sales_channel harus unik. "
            f"Perbaiki mapping berikut: {details}"
        )


@task
def refresh_dashboard_materialized_views() -> None:
    logger = get_run_logger()
    engine = get_engine()

    with engine.begin() as conn:
        for mv in DASHBOARD_MATERIALIZED_VIEWS:
            logger.info("Refresh materialized view dashboard: %s", mv)
            conn.execute(text(f"REFRESH MATERIALIZED VIEW {mv}"))


@flow(name="Generate_Daily_Target")
def generate_daily_target_flow(
    reference_date: str | None = None,
    overwrite_targets: bool = False,
    refresh_planning: bool = True,
    refresh_dashboard: bool = True,
) -> dict[str, int]:
    logger = get_run_logger()
    if reference_date:
        date.fromisoformat(reference_date)

    logger.info(
        "Start daily target generation. reference_date=%s overwrite_targets=%s",
        reference_date or "CURRENT_DATE",
        overwrite_targets,
    )

    if refresh_planning:
        refresh_planning_materialized_views()

    production_rows = generate_production_daily_target(
        reference_date=reference_date,
        overwrite_targets=overwrite_targets,
    )
    validate_distribution_planning_mapping()
    distribution_rows = generate_distribution_daily_target(
        reference_date=reference_date,
        overwrite_targets=overwrite_targets,
    )

    if refresh_dashboard:
        refresh_dashboard_materialized_views()

    result = {
        "production_rows": production_rows,
        "distribution_rows": distribution_rows,
    }
    logger.info("Daily target generation finished: %s", result)
    return result


if __name__ == "__main__":
    generate_daily_target_flow()
