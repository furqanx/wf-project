"""Prefect flow for Accurate offline sales extraction and phase-1 loading."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from prefect import flow, get_run_logger, task

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEZONE = "Asia/Jakarta"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_STAGING_ROOT = PROJECT_ROOT / "data/staging/accurate"
DEFAULT_OUTPUT_ROOT = "/tmp/accurate_offline_sales_pipeline"
DEFAULT_DATABASE = "wellfarm_alternatives"


@task(name="run_accurate_offline_sales_pipeline")
def run_pipeline_command(
    *,
    start_date: str,
    end_date: str,
    page_size: int,
    batch_size: int,
    start_offset: int,
    max_pages: int | None,
    max_batches: int | None,
    database: str,
    target_schema: str,
    output_root: str,
    staging_root: str,
    execute: bool,
    allow_unmapped: bool,
    skip_existing_output: bool,
) -> dict[str, Any]:
    """Run the existing offline sales pipeline CLI and stream logs to Prefect."""
    logger = get_run_logger()
    command = [
        sys.executable,
        "scripts/backfill/accurate_offline_sales_pipeline.py",
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--page-size",
        str(page_size),
        "--batch-size",
        str(batch_size),
        "--start-offset",
        str(start_offset),
        "--database",
        database,
        "--target-schema",
        target_schema,
        "--output-root",
        output_root,
        "--staging-root",
        staging_root,
    ]
    if max_pages is not None:
        command.extend(["--max-pages", str(max_pages)])
    if max_batches is not None:
        command.extend(["--max-batches", str(max_batches)])
    if execute:
        command.append("--execute")
    if allow_unmapped:
        command.append("--allow-unmapped")
    if skip_existing_output:
        command.append("--skip-existing-output")

    logger.info("Run Accurate offline sales pipeline: %s", " ".join(command))
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    output_tail: list[str] = []
    for line in process.stdout:
        clean_line = line.rstrip()
        logger.info(clean_line)
        output_tail.append(clean_line)
        if len(output_tail) > 50:
            output_tail.pop(0)

    return_code = process.wait()
    if return_code:
        tail = "\n".join(output_tail)
        raise RuntimeError(f"Accurate offline sales pipeline failed with exit code {return_code}.\n{tail}")

    return {
        "start_date": start_date,
        "end_date": end_date,
        "database": database,
        "target_schema": target_schema,
        "output_root": output_root,
        "staging_root": staging_root,
        "execute": execute,
    }


@flow(name="Accurate_Offline_Sales_Incremental")
def accurate_offline_sales_incremental_flow(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    timezone: str = DEFAULT_TIMEZONE,
    page_size: int = 100,
    batch_size: int = 500,
    start_offset: int = 0,
    max_pages: int | None = None,
    max_batches: int | None = None,
    database: str = DEFAULT_DATABASE,
    target_schema: str = "public",
    output_root: str = DEFAULT_OUTPUT_ROOT,
    staging_root: str = str(DEFAULT_STAGING_ROOT),
    execute: bool = True,
    allow_unmapped: bool = False,
    skip_existing_output: bool = False,
) -> dict[str, Any]:
    """Fetch Accurate sales receipts, save staging raw files, and load offline sales facts."""
    window_start, window_end = resolve_window(
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        timezone=timezone,
    )
    return run_pipeline_command(
        start_date=window_start,
        end_date=window_end,
        page_size=page_size,
        batch_size=batch_size,
        start_offset=start_offset,
        max_pages=max_pages,
        max_batches=max_batches,
        database=database,
        target_schema=target_schema,
        output_root=output_root,
        staging_root=staging_root,
        execute=execute,
        allow_unmapped=allow_unmapped,
        skip_existing_output=skip_existing_output,
    )


def resolve_window(
    *,
    start_date: str | None,
    end_date: str | None,
    lookback_days: int,
    timezone: str,
) -> tuple[str, str]:
    """Resolve an explicit or rolling receipt-date window."""
    if bool(start_date) != bool(end_date):
        raise ValueError("start_date and end_date must be provided together.")
    if start_date and end_date:
        return normalize_date_text(start_date), normalize_date_text(end_date)
    if lookback_days < 0:
        raise ValueError("lookback_days must be zero or greater.")

    today = datetime.now(ZoneInfo(timezone)).date()
    return (today - timedelta(days=lookback_days)).isoformat(), today.isoformat()


def normalize_date_text(value: str | date) -> str:
    """Normalize a date value to YYYY-MM-DD."""
    if isinstance(value, date):
        return value.isoformat()
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or DD/MM/YYYY.")


if __name__ == "__main__":
    accurate_offline_sales_incremental_flow()
