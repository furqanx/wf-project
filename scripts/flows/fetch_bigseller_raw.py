"""Prefect flows for BigSeller raw API extraction."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from prefect import flow, get_run_logger, task

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.api.config import get_api_extract_config
from scripts.api.models import ManifestRecord
from scripts.api.runners.bigseller import run_bigseller_extract
from scripts.database.connection import get_engine


DEFAULT_TIMEZONE = "Asia/Jakarta"
DEFAULT_INCREMENTAL_LOOKBACK_DAYS = 3


@task(name="fetch_bigseller_incremental_group")
def fetch_bigseller_incremental_group(
    *,
    endpoint_group: str | None,
    start_date: str,
    end_date: str,
    database: str | None,
    raw_root: str | None,
    write_manifest: bool,
    compress: bool,
    max_pages: int | None,
) -> list[ManifestRecord]:
    """Fetch BigSeller incremental endpoints for a date window."""
    logger = get_run_logger()
    output_root = raw_root or str(get_api_extract_config().storage.bigseller_raw_root)
    engine = get_engine(database) if write_manifest else None

    logger.info(
        "Fetch BigSeller incremental. group=%s start_date=%s end_date=%s raw_root=%s max_pages=%s",
        endpoint_group or "ALL",
        start_date,
        end_date,
        output_root,
        max_pages,
    )
    return run_bigseller_extract(
        endpoint_group=endpoint_group,
        fetch_mode="incremental",
        start_date=start_date,
        end_date=end_date,
        raw_root=output_root,
        engine=engine,
        write_manifest=write_manifest,
        compress=compress,
        max_pages=max_pages,
    )


@task(name="validate_bigseller_fetch")
def validate_bigseller_fetch(
    records: list[ManifestRecord],
    *,
    write_manifest: bool,
    fail_on_error: bool,
) -> dict[str, Any]:
    """Summarize BigSeller fetch results and optionally fail the flow."""
    logger = get_run_logger()
    success_count = sum(1 for record in records if record.success)
    failed_records = [record for record in records if not record.success]
    total_records = sum(record.record_count or 0 for record in records if record.success)

    summary = {
        "endpoint_count": len(records),
        "success_count": success_count,
        "failed_count": len(failed_records),
        "record_count": total_records,
        "manifest": "ON" if write_manifest else "OFF",
    }
    logger.info("BigSeller fetch summary: %s", summary)

    for record in failed_records:
        logger.error("Failed endpoint=%s error=%s", record.endpoint, record.error_message)
    if failed_records and fail_on_error:
        raise RuntimeError(f"{len(failed_records)} BigSeller endpoint(s) failed.")
    return summary


@flow(name="BigSeller_Incremental")
def bigseller_incremental_flow(
    *,
    endpoint_group: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    lookback_days: int = DEFAULT_INCREMENTAL_LOOKBACK_DAYS,
    timezone: str = DEFAULT_TIMEZONE,
    database: str | None = None,
    raw_root: str | None = None,
    write_manifest: bool = True,
    compress: bool = False,
    max_pages: int | None = None,
    fail_on_error: bool = True,
) -> dict[str, Any]:
    """Prefect flow for scheduled BigSeller incremental extraction."""
    window_start, window_end = resolve_incremental_window(
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        timezone=timezone,
    )
    records = fetch_bigseller_incremental_group(
        endpoint_group=endpoint_group,
        start_date=window_start,
        end_date=window_end,
        database=database,
        raw_root=raw_root,
        write_manifest=write_manifest,
        compress=compress,
        max_pages=max_pages,
    )
    return validate_bigseller_fetch(
        records,
        write_manifest=write_manifest,
        fail_on_error=fail_on_error,
    )


def resolve_incremental_window(
    *,
    start_date: str | None,
    end_date: str | None,
    lookback_days: int,
    timezone: str,
) -> tuple[str, str]:
    """Resolve the default incremental date window."""
    if bool(start_date) != bool(end_date):
        raise ValueError("start_date and end_date must be provided together.")
    if start_date and end_date:
        return normalize_date_text(start_date), normalize_date_text(end_date)
    if lookback_days < 0:
        raise ValueError("lookback_days must be zero or greater.")

    today = datetime.now(ZoneInfo(timezone)).date()
    return (today - timedelta(days=lookback_days)).isoformat(), today.isoformat()


def normalize_date_text(value: str) -> str:
    """Validate and normalize YYYY-MM-DD date text."""
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


if __name__ == "__main__":
    bigseller_incremental_flow()
