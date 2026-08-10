"""Backfill existing local files into filesystem staging and file_manifest.

Default mode is dry-run. Use --execute to copy files and insert manifest rows.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

PROJECT_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORTS))

from scripts.backfill.parsers import BackfillFile, parse_crewdible_file, parse_sales_online_file
from scripts.config import DEFAULT_SOURCE_ROOT, SUPPORTED_EXTENSIONS
from scripts.crewdible.file_staging import (
    CrewdibleUploadMetadata,
    build_crewdible_staging_path,
    inspect_crewdible_file,
)
from scripts.database.connection import get_engine
from scripts.staging.manifest import (
    PROJECT_ROOT,
    calculate_sha256,
    ensure_file_manifest_tables,
    get_env_path,
    slugify,
    unique_path,
)
from src.file_inspector import count_rows_in_file


DEFAULT_SALES_STAGING_ROOT = PROJECT_ROOT / "data" / "staging" / "sales_online"
SALES_STAGING_ROOT = get_env_path("SALES_ONLINE_FILE_STAGING_ROOT", DEFAULT_SALES_STAGING_ROOT)

SOURCE_CHOICES = {"all", "crewdible", "sales_online", "lazada", "shopee", "tiktok_tokopedia"}


@dataclass(frozen=True)
class BackfillDecision:
    item: BackfillFile
    status: str
    rows_detected: int
    checksum_sha256: str
    file_size_bytes: int
    staged_path: Path | None = None
    manifest_id: int | None = None
    error_message: str | None = None


def main() -> None:
    args = parse_args()
    source_root = args.source_root.resolve()
    files = discover_backfill_files(source_root, args.source)

    if args.limit:
        files = files[: args.limit]

    engine = get_engine(args.database) if args.execute or args.check_db else None
    if engine is not None:
        ensure_file_manifest_tables(engine)

    print(f"Mode        : {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"Source root : {source_root}")
    print(f"Source      : {args.source}")
    print(f"Files found : {len(files)}")

    decisions: list[BackfillDecision] = []
    for index, item in enumerate(files, start=1):
        decision = backfill_one(
            item,
            engine=engine,
            execute=args.execute,
            skip_row_count=args.skip_row_count,
        )
        decisions.append(decision)
        print(format_decision(index, decision))

    print_summary(decisions)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill local data files into staging.file_manifest.")
    parser.add_argument(
        "--source",
        choices=sorted(SOURCE_CHOICES),
        default="all",
        help="Which source to backfill.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help="Root folder containing crewdible/lazada/shopee/tiktok-tokopedia folders.",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Override target PostgreSQL database. Defaults to IMPORT_DB_NAME/DB_NAME.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Copy files into staging and insert manifest rows.",
    )
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="In dry-run mode, also check existing manifest rows by checksum.",
    )
    parser.add_argument(
        "--skip-row-count",
        action="store_true",
        help="Skip file row counting for a faster planning run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of files, useful for smoke tests.",
    )
    return parser.parse_args()


def discover_backfill_files(source_root: Path, source: str) -> list[BackfillFile]:
    items: list[BackfillFile] = []

    if source in {"all", "crewdible"}:
        for path in iter_files(source_root / "crewdible"):
            item = parse_crewdible_file(path)
            if item:
                items.append(item)

    sales_sources = {"all", "sales_online", "lazada", "shopee", "tiktok_tokopedia"}
    if source in sales_sources:
        marketplace_folders = ["lazada", "shopee", "tiktok-tokopedia"]
        if source in {"lazada", "shopee"}:
            marketplace_folders = [source]
        elif source == "tiktok_tokopedia":
            marketplace_folders = ["tiktok-tokopedia"]

        for folder in marketplace_folders:
            for path in iter_files(source_root / folder):
                item = parse_sales_online_file(path, source_root)
                if item:
                    items.append(item)

    return sorted(items, key=lambda item: str(item.source_path))


def iter_files(root: Path):
    if not root.exists():
        return

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def backfill_one(
    item: BackfillFile,
    *,
    engine: Engine | None,
    execute: bool,
    skip_row_count: bool,
) -> BackfillDecision:
    try:
        checksum = calculate_sha256(item.source_path)
        file_size = item.source_path.stat().st_size
        rows_detected = 0 if skip_row_count else count_rows(item)

        if engine is not None and manifest_exists(engine, item, checksum):
            return BackfillDecision(
                item=item,
                status="skipped_existing",
                rows_detected=rows_detected,
                checksum_sha256=checksum,
                file_size_bytes=file_size,
            )

        if not execute:
            return BackfillDecision(
                item=item,
                status="ready",
                rows_detected=rows_detected,
                checksum_sha256=checksum,
                file_size_bytes=file_size,
            )

        if engine is None:
            raise RuntimeError("Engine is required in execute mode.")

        staged_path = build_staging_path(item)
        shutil.copy2(item.source_path, staged_path)
        manifest_id = insert_manifest(engine, item, staged_path, checksum, file_size, rows_detected)

        return BackfillDecision(
            item=item,
            status="staged",
            rows_detected=rows_detected,
            checksum_sha256=checksum,
            file_size_bytes=file_size,
            staged_path=staged_path,
            manifest_id=manifest_id,
        )
    except Exception as exc:
        return BackfillDecision(
            item=item,
            status="error",
            rows_detected=0,
            checksum_sha256="",
            file_size_bytes=0,
            error_message=str(exc),
        )


def count_rows(item: BackfillFile) -> int:
    if item.source_system == "crewdible":
        inspection = inspect_crewdible_file(item.source_path)
        if not inspection["valid"]:
            raise ValueError(inspection["error_message"])
        return int(inspection["physical_rows"] or 0)

    if item.source_path.suffix.lower() == ".csv":
        return count_csv_rows(item.source_path)

    return count_rows_in_file(str(item.source_path), item.fase, item.marketplace)


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.reader(file_obj)
        rows = list(reader)
    if not rows:
        return 0
    return sum(1 for row in rows[1:] if any(str(value).strip() for value in row))


def build_staging_path(item: BackfillFile) -> Path:
    if item.source_system == "crewdible":
        metadata = CrewdibleUploadMetadata(
            period_year=int(item.period_year or 0),
            period_month=item.period_month,
            data_category=item.data_category,
        )
        return build_crewdible_staging_path(item.source_path.name, metadata)

    uploaded_at = datetime.now()
    marketplace = slugify(item.marketplace)
    fase = slugify(item.fase)
    store = slugify(item.store_name)
    original_stem = slugify(item.source_path.stem)
    file_ext = item.source_path.suffix.lower() or ".xlsx"

    folder = (
        SALES_STAGING_ROOT
        / marketplace
        / fase
        / f"store={store}"
        / f"uploaded_date={uploaded_at:%Y-%m-%d}"
    )
    folder.mkdir(parents=True, exist_ok=True)
    return unique_path(folder / f"{marketplace}_{fase}_{store}__{original_stem}{file_ext}")


def manifest_exists(engine: Engine, item: BackfillFile, checksum: str) -> bool:
    query = text("""
        SELECT 1
        FROM staging.file_manifest
        WHERE source_system = :source_system
          AND COALESCE(data_category, '') = COALESCE(:data_category, '')
          AND marketplace = :marketplace
          AND fase = :fase
          AND store_name = :store_name
          AND checksum_sha256 = :checksum
          AND file_status <> 'invalid'
        LIMIT 1
    """)
    with engine.connect() as conn:
        return conn.execute(query, manifest_params(item, checksum=checksum)).first() is not None


def insert_manifest(
    engine: Engine,
    item: BackfillFile,
    staged_path: Path,
    checksum: str,
    file_size: int,
    rows_detected: int,
) -> int:
    query = text("""
        INSERT INTO staging.file_manifest (
            source_system,
            data_category,
            period_year,
            period_month,
            marketplace,
            fase,
            store_name,
            original_filename,
            staged_filename,
            file_path,
            file_ext,
            file_size_bytes,
            checksum_sha256,
            rows_detected,
            file_status,
            transform_status,
            checked_at
        )
        VALUES (
            :source_system,
            :data_category,
            :period_year,
            :period_month,
            :marketplace,
            :fase,
            :store_name,
            :original_filename,
            :staged_filename,
            :file_path,
            :file_ext,
            :file_size_bytes,
            :checksum,
            :rows_detected,
            'staged',
            'pending',
            NOW()
        )
        RETURNING manifest_id
    """)
    params = manifest_params(
        item,
        checksum=checksum,
        staged_path=staged_path,
        file_size=file_size,
        rows_detected=rows_detected,
    )
    with engine.begin() as conn:
        return int(conn.execute(query, params).scalar_one())


def manifest_params(
    item: BackfillFile,
    *,
    checksum: str,
    staged_path: Path | None = None,
    file_size: int | None = None,
    rows_detected: int | None = None,
) -> dict[str, object]:
    return {
        "source_system": item.source_system,
        "data_category": item.data_category,
        "period_year": item.period_year,
        "period_month": item.period_month,
        "marketplace": item.marketplace,
        "fase": item.fase,
        "store_name": item.store_name,
        "original_filename": item.source_path.name,
        "staged_filename": staged_path.name if staged_path else None,
        "file_path": str(staged_path) if staged_path else None,
        "file_ext": item.source_path.suffix.lower(),
        "file_size_bytes": file_size,
        "checksum": checksum,
        "rows_detected": rows_detected,
    }


def format_decision(index: int, decision: BackfillDecision) -> str:
    item = decision.item
    period = f"{item.period_year or '-'}-{item.period_month:02d}" if item.period_month else str(item.period_year or "-")
    parts = [
        f"{index:04d}",
        decision.status,
        item.source_system,
        item.marketplace,
        item.fase,
        item.store_name,
        period,
        f"rows={decision.rows_detected}",
        str(item.source_path),
    ]
    if decision.manifest_id:
        parts.insert(2, f"manifest_id={decision.manifest_id}")
    if decision.error_message:
        parts.append(f"error={decision.error_message}")
    return " | ".join(parts)


def print_summary(decisions: list[BackfillDecision]) -> None:
    counts: dict[str, int] = {}
    rows_by_status: dict[str, int] = {}
    for decision in decisions:
        counts[decision.status] = counts.get(decision.status, 0) + 1
        rows_by_status[decision.status] = rows_by_status.get(decision.status, 0) + decision.rows_detected

    print("\nSummary")
    print("-------")
    for status in sorted(counts):
        print(f"{status:16s}: {counts[status]:5d} files | {rows_by_status[status]:10d} rows")
    print(f"{'total':16s}: {len(decisions):5d} files | {sum(d.rows_detected for d in decisions):10d} rows")


if __name__ == "__main__":
    main()
