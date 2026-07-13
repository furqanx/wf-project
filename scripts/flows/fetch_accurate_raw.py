"""Prefect flows for Accurate raw API extraction."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from prefect import flow, get_run_logger, task

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.api.config import get_api_extract_config
from scripts.api.models import ManifestRecord
from scripts.api.runners.accurate import run_accurate_extract
from scripts.api.storage.master_snapshot_diff import process_pending_master_snapshot_diffs
from scripts.api.storage.master_snapshot_index import insert_master_snapshot_indexes
from scripts.database.connection import get_engine


DEFAULT_TIMEZONE = "Asia/Jakarta"
DEFAULT_INCREMENTAL_LOOKBACK_DAYS = 3


@task(name="fetch_master_snapshot")
def fetch_master_snapshot(
    *,
    database: str | None,
    raw_root: str | None,
    write_manifest: bool,
    compress: bool,
    max_pages: int | None,
) -> list[ManifestRecord]:
    """Fetch all Accurate endpoints marked fetch_mode=full."""
    logger = get_run_logger()
    output_root = raw_root or str(get_api_extract_config().storage.accurate_raw_root)
    engine = get_engine(database) if write_manifest else None

    logger.info("Fetch Accurate master snapshot. raw_root=%s max_pages=%s", output_root, max_pages)
    return run_accurate_extract(
        fetch_mode="full",
        raw_root=output_root,
        engine=engine,
        write_manifest=write_manifest,
        compress=compress,
        max_pages=max_pages,
    )


@task(name="fetch_incremental_group")
def fetch_incremental_group(
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
    """Fetch Accurate incremental endpoints for a date window."""
    logger = get_run_logger()
    output_root = raw_root or str(get_api_extract_config().storage.accurate_raw_root)
    engine = get_engine(database) if write_manifest else None

    logger.info(
        "Fetch Accurate incremental. group=%s start_date=%s end_date=%s raw_root=%s max_pages=%s",
        endpoint_group or "ALL",
        start_date,
        end_date,
        output_root,
        max_pages,
    )
    return run_accurate_extract(
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


@task(name="validate_manifest_insert")
def validate_manifest_insert(
    records: list[ManifestRecord],
    *,
    write_manifest: bool,
    fail_on_error: bool,
) -> dict[str, Any]:
    """Summarize flow result and fail the flow when endpoint fetches fail."""
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
    logger.info("Accurate fetch summary: %s", summary)

    for record in failed_records:
        logger.error("Failed endpoint=%s error=%s", record.endpoint, record.error_message)
    if failed_records and fail_on_error:
        raise RuntimeError(f"{len(failed_records)} Accurate endpoint(s) failed.")
    return summary


@task(name="index_master_snapshot")
def index_master_snapshot(
    records: list[ManifestRecord],
    *,
    database: str | None,
    write_manifest: bool,
) -> int:
    """Insert successful Accurate master snapshots into master_snapshot_index."""
    logger = get_run_logger()
    if not write_manifest:
        logger.info("Skip master snapshot index because manifest writing is OFF.")
        return 0

    engine = get_engine(database)
    inserted_count = insert_master_snapshot_indexes(engine, records)
    logger.info("Inserted master snapshot index rows: %s", inserted_count)
    return inserted_count


@task(name="process_master_snapshot_diff")
def process_master_snapshot_diff(
    *,
    database: str | None,
    source_system: str = "accurate",
    limit: int | None = None,
) -> dict[str, int]:
    """Compare pending master snapshots and insert rows into master_snapshot_diff."""
    logger = get_run_logger()
    engine = get_engine(database)
    summary = process_pending_master_snapshot_diffs(
        engine,
        source_system=source_system,
        limit=limit,
    )
    logger.info("Master snapshot diff summary: %s", summary)
    return summary


@flow(name="Accurate_Master_Snapshot")
def accurate_master_snapshot_flow(
    *,
    database: str | None = None,
    raw_root: str | None = None,
    write_manifest: bool = True,
    compress: bool = False,
    max_pages: int | None = None,
    fail_on_error: bool = True,
    process_diff: bool = True,
) -> dict[str, Any]:
    """Prefect flow for scheduled Accurate master snapshot extraction."""
    records = fetch_master_snapshot(
        database=database,
        raw_root=raw_root,
        write_manifest=write_manifest,
        compress=compress,
        max_pages=max_pages,
    )
    summary = validate_manifest_insert(
        records,
        write_manifest=write_manifest,
        fail_on_error=fail_on_error,
    )
    snapshot_index_rows = index_master_snapshot(
        records,
        database=database,
        write_manifest=write_manifest,
    )
    summary["snapshot_index_rows"] = snapshot_index_rows
    if process_diff and write_manifest:
        summary["snapshot_diff"] = process_master_snapshot_diff(database=database)
    else:
        summary["snapshot_diff"] = {
            "pending_snapshot_count": 0,
            "processed_snapshot_count": 0,
            "skipped_snapshot_count": 0,
            "inserted_diff_count": 0,
            "deleted_diff_count": 0,
            "total_diff_count": 0,
        }
    return summary


@flow(name="Accurate_Incremental")
def accurate_incremental_flow(
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
    """Prefect flow for scheduled Accurate incremental extraction."""
    window_start, window_end = resolve_incremental_window(
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        timezone=timezone,
    )
    records = fetch_incremental_group(
        endpoint_group=endpoint_group,
        start_date=window_start,
        end_date=window_end,
        database=database,
        raw_root=raw_root,
        write_manifest=write_manifest,
        compress=compress,
        max_pages=max_pages,
    )
    return validate_manifest_insert(
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


def normalize_date_text(value: str | date) -> str:
    """Normalize a date value to YYYY-MM-DD for the runner CLI contract."""
    if isinstance(value, date):
        return value.isoformat()
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or DD/MM/YYYY.")
