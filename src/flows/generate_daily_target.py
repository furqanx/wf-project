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

SQL_DIR = Path(__file__).resolve().parent / "sql" / "generate_daily_target"


def _load_sql(filename: str) -> str:
    return (SQL_DIR / filename).read_text(encoding="utf-8")


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
    query = text(_load_sql("generate_production_daily_target.sql"))

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
    query = text(_load_sql("generate_distribution_daily_target.sql"))

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
def validate_distribution_planning_ids() -> None:
    engine = get_engine()
    query = text(_load_sql("validate_distribution_planning_ids.sql"))

    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()

    if rows:
        details = "; ".join(
            f"{row['warehouse_name']} / {row['store_name']} / product_id={row['product_id']}"
            for row in rows
        )
        raise RuntimeError(
            "mv_distribution_planning masih memiliki ID kosong. "
            f"Perbaiki baris berikut: {details}"
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
    validate_distribution_planning_ids()
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
