"""Backfill Accurate raw API responses into staging-style folders."""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.api.clients.accurate import AccurateClient
from scripts.api.models import EndpointSpec, ManifestRecord, RawFileInfo
from scripts.api.registry.accurate import get_endpoint_specs
from scripts.api.runners.accurate import (
    build_effective_request_params,
    build_params,
    fetch_responses,
    hash_request,
    validate_fetch_mode,
)
from scripts.api.storage.manifest import insert_manifest_record
from scripts.api.storage.raw_files import count_records, sha256_file
from scripts.database.connection import get_engine
from scripts.utils.env import load_dotenv_file


DEFAULT_STAGING_ROOT = PROJECT_ROOT / "data/staging/accurate"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonthWindow:
    year: int
    month: int
    start_date: date
    end_date: date

    @property
    def year_partition(self) -> str:
        return f"year={self.year:04d}"

    @property
    def month_partition(self) -> str:
        return f"month={self.month:02d}"

    @property
    def file_period(self) -> str:
        return f"{self.start_date:%Y%m%d}_{self.end_date:%Y%m%d}"


def parse_args() -> argparse.Namespace:
    load_dotenv_file()
    parser = argparse.ArgumentParser(description="Backfill Accurate raw data into staging folders.")
    parser.add_argument("--mode", choices=["master", "incremental"], required=True)
    parser.add_argument("--staging-root", default=str(DEFAULT_STAGING_ROOT))
    parser.add_argument("--group", dest="endpoint_group", default=None)
    parser.add_argument("--endpoint", dest="endpoint_name", default=None)
    parser.add_argument("--start-month", default=None, help="Inclusive month, format YYYY-MM.")
    parser.add_argument("--end-month", default=None, help="Inclusive month, format YYYY-MM.")
    parser.add_argument("--snapshot-date", default=None, help="Master snapshot date, format YYYY-MM-DD.")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--compress", action="store_true")
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--database", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "master":
        records = backfill_master(
            staging_root=Path(args.staging_root),
            snapshot_date=parse_snapshot_date(args.snapshot_date),
            endpoint_group=args.endpoint_group,
            endpoint_name=args.endpoint_name,
            max_pages=args.max_pages,
            compress=args.compress,
            write_manifest=args.write_manifest,
            database=args.database,
            dry_run=args.dry_run,
        )
    else:
        records = backfill_incremental(
            staging_root=Path(args.staging_root),
            month_windows=parse_month_windows(args.start_month, args.end_month),
            endpoint_group=args.endpoint_group,
            endpoint_name=args.endpoint_name,
            max_pages=args.max_pages,
            compress=args.compress,
            write_manifest=args.write_manifest,
            database=args.database,
            dry_run=args.dry_run,
        )

    success_count = sum(1 for record in records if record.success)
    failed_count = len(records) - success_count
    total_records = sum(record.record_count or 0 for record in records if record.success)
    logger.info(
        "Backfill finished. files=%s success=%s failed=%s records=%s",
        len(records),
        success_count,
        failed_count,
        total_records,
    )
    for record in records:
        if not record.success:
            logger.error("Failed endpoint=%s error=%s", record.endpoint, record.error_message)


def backfill_master(
    *,
    staging_root: Path,
    snapshot_date: date,
    endpoint_group: str | None,
    endpoint_name: str | None,
    max_pages: int | None,
    compress: bool,
    write_manifest: bool,
    database: str | None,
    dry_run: bool,
) -> list[ManifestRecord]:
    specs = get_backfill_specs(
        fetch_mode="full",
        endpoint_group=endpoint_group,
        endpoint_name=endpoint_name,
    )
    logger.info("Accurate master backfill specs=%s snapshot_date=%s", len(specs), snapshot_date)
    if dry_run:
        for spec in specs:
            logger.info("DRY RUN master endpoint=%s output=%s", spec.name, master_output_dir(staging_root, spec, snapshot_date))
        return []

    client = AccurateClient.from_env()
    client.get_host()
    engine = get_engine(database) if write_manifest else None
    run_id = str(uuid4())

    records: list[ManifestRecord] = []
    for spec in specs:
        record = fetch_and_write_staging(
            client=client,
            spec=spec,
            request_params={},
            output_dir=master_output_dir(staging_root, spec, snapshot_date),
            file_prefix=f"accurate_{spec.name}_snapshot_{snapshot_date:%Y%m%d}",
            compress=compress,
            max_pages=max_pages,
            run_id=run_id,
        )
        records.append(insert_manifest_if_requested(engine, record) if write_manifest else record)
    return records


def backfill_incremental(
    *,
    staging_root: Path,
    month_windows: list[MonthWindow],
    endpoint_group: str | None,
    endpoint_name: str | None,
    max_pages: int | None,
    compress: bool,
    write_manifest: bool,
    database: str | None,
    dry_run: bool,
) -> list[ManifestRecord]:
    specs = get_backfill_specs(
        fetch_mode="incremental",
        endpoint_group=endpoint_group,
        endpoint_name=endpoint_name,
    )
    logger.info("Accurate incremental backfill specs=%s month_windows=%s", len(specs), len(month_windows))
    if dry_run:
        for window in month_windows:
            for spec in specs:
                logger.info(
                    "DRY RUN incremental endpoint=%s start=%s end=%s output=%s",
                    spec.name,
                    window.start_date,
                    window.end_date,
                    incremental_output_dir(staging_root, spec, window),
                )
        return []

    client = AccurateClient.from_env()
    client.get_host()
    engine = get_engine(database) if write_manifest else None
    run_id = str(uuid4())

    records: list[ManifestRecord] = []
    for window in month_windows:
        for spec in specs:
            request_params = build_effective_request_params(
                spec=spec,
                request_params={},
                start_date=window.start_date,
                end_date=window.end_date,
            )
            validate_fetch_mode(spec, request_params, allow_manual=False)
            record = fetch_and_write_staging(
                client=client,
                spec=spec,
                request_params=request_params,
                output_dir=incremental_output_dir(staging_root, spec, window),
                file_prefix=f"accurate_{spec.name}_{window.file_period}",
                compress=compress,
                max_pages=max_pages,
                run_id=run_id,
            )
            records.append(insert_manifest_if_requested(engine, record) if write_manifest else record)
    return records


def get_backfill_specs(
    *,
    fetch_mode: str,
    endpoint_group: str | None,
    endpoint_name: str | None,
) -> list[EndpointSpec]:
    specs = get_endpoint_specs(
        endpoint_group=endpoint_group,
        endpoint_name=endpoint_name,
        fetch_mode=fetch_mode,
    )
    # Backfill follows the production rule: active and optional only, never review/manual.
    return [
        spec
        for spec in specs
        if spec.storage_folder.startswith(("active/", "optional/"))
    ]


def fetch_and_write_staging(
    *,
    client: AccurateClient,
    spec: EndpointSpec,
    request_params: dict[str, Any],
    output_dir: Path,
    file_prefix: str,
    compress: bool,
    max_pages: int | None,
    run_id: str,
) -> ManifestRecord:
    fetched_at = datetime.now().astimezone()
    endpoint = spec.render_endpoint()
    params = build_params(spec, request_params)
    started = time.monotonic()

    try:
        logger.info("Fetch Accurate endpoint=%s output=%s", spec.name, output_dir)
        responses, status_code = fetch_responses(
            client=client,
            spec=spec,
            endpoint=endpoint,
            params=params,
            max_pages=max_pages,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        raw_file = write_staging_response(
            output_dir=output_dir,
            file_prefix=file_prefix,
            responses=responses,
            compress=compress,
        )
        return ManifestRecord(
            source_system="accurate",
            endpoint_group=spec.endpoint_group,
            endpoint=endpoint,
            request_method=spec.method,
            request_params={"params": params, "storage_group": str(output_dir)},
            request_hash=hash_request(endpoint, params),
            fetched_at=fetched_at,
            fetched_date=fetched_at.date(),
            storage_path=str(raw_file.storage_path),
            file_name=raw_file.file_name,
            file_format=raw_file.file_format,
            is_compressed=raw_file.is_compressed,
            status_code=status_code,
            success=True,
            record_count=raw_file.record_count,
            file_size_bytes=raw_file.file_size_bytes,
            checksum_sha256=raw_file.checksum_sha256,
            duration_ms=duration_ms,
            pagination_key=spec.pagination_strategy,
            run_id=run_id,
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return ManifestRecord(
            source_system="accurate",
            endpoint_group=spec.endpoint_group,
            endpoint=endpoint,
            request_method=spec.method,
            request_params={"params": params, "storage_group": str(output_dir)},
            request_hash=hash_request(endpoint, params),
            fetched_at=fetched_at,
            fetched_date=fetched_at.date(),
            success=False,
            duration_ms=duration_ms,
            pagination_key=spec.pagination_strategy,
            run_id=run_id,
            error_message=str(exc),
        )


def write_staging_response(
    *,
    output_dir: Path,
    file_prefix: str,
    responses: list[dict[str, Any]],
    compress: bool,
) -> RawFileInfo:
    output_dir.mkdir(parents=True, exist_ok=True)
    is_jsonl = len(responses) > 1
    suffix = ".jsonl" if is_jsonl else ".json"
    if compress:
        suffix = f"{suffix}.gz"

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"{file_prefix}_{timestamp}{suffix}"
    if is_jsonl:
        content = "\n".join(json.dumps(response, ensure_ascii=False) for response in responses)
    else:
        content = json.dumps(responses[0] if responses else {}, ensure_ascii=False, indent=2)

    if compress:
        with gzip.open(output_path, "wt", encoding="utf-8") as f:
            f.write(content)
    else:
        output_path.write_text(content, encoding="utf-8")

    return RawFileInfo(
        storage_path=output_dir,
        file_name=output_path.name,
        file_format="jsonl" if is_jsonl else "json",
        is_compressed=compress,
        file_size_bytes=output_path.stat().st_size,
        checksum_sha256=sha256_file(output_path),
        record_count=sum(count_records(response) for response in responses),
    )


def insert_manifest_if_requested(engine: Any, record: ManifestRecord) -> ManifestRecord:
    if engine is None:
        raise RuntimeError("engine is required when write_manifest=True.")
    manifest_id = insert_manifest_record(engine, record)
    return record.model_copy(update={"manifest_id": manifest_id})


def master_output_dir(staging_root: Path, spec: EndpointSpec, snapshot_date: date) -> Path:
    return staging_root / spec.endpoint_group / f"entity={spec.name}" / f"snapshot_date={snapshot_date.isoformat()}"


def incremental_output_dir(staging_root: Path, spec: EndpointSpec, window: MonthWindow) -> Path:
    return (
        staging_root
        / spec.endpoint_group
        / f"entity={spec.name}"
        / window.year_partition
        / window.month_partition
    )


def parse_snapshot_date(value: str | None) -> date:
    if value is None:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_month_windows(start_month: str | None, end_month: str | None) -> list[MonthWindow]:
    if not start_month or not end_month:
        raise ValueError("--start-month and --end-month are required for incremental backfill.")
    start_year, start_month_number = parse_month_text(start_month)
    end_year, end_month_number = parse_month_text(end_month)
    start_index = start_year * 12 + start_month_number
    end_index = end_year * 12 + end_month_number
    if start_index > end_index:
        raise ValueError("--start-month must be earlier than or equal to --end-month.")

    windows: list[MonthWindow] = []
    for index in range(start_index, end_index + 1):
        year = index // 12
        month = index % 12
        if month == 0:
            year -= 1
            month = 12
        start_date = date(year, month, 1)
        end_date = month_end(year, month)
        windows.append(MonthWindow(year=year, month=month, start_date=start_date, end_date=end_date))
    return windows


def parse_month_text(value: str) -> tuple[int, int]:
    parsed = datetime.strptime(value, "%Y-%m")
    return parsed.year, parsed.month


def month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1).replace(day=1) - date.resolution


if __name__ == "__main__":
    main()
