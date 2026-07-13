"""CLI entry point for dry-running marketplace staging imports."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.config import DEFAULT_SOURCE_ROOT, SUPPORTED_MARKETPLACES, SUPPORTED_PHASES
from scripts.file_discovery import MarketplaceFile, discover_files
from scripts.loaders import lazada as lazada_loader
from scripts.loaders import shopee as shopee_loader
from scripts.loaders import tiktok_tokopedia as tiktok_tokopedia_loader
from scripts.loaders.common import LoadedFrame

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

warnings.filterwarnings(
    "ignore",
    message="Workbook contains no default style, apply openpyxl's default",
    category=UserWarning,
    module="openpyxl.styles.stylesheet",
)


def parse_args():
    parser = argparse.ArgumentParser(description="Dry-run import file marketplace ke raw staging.")
    parser.add_argument(
        "--source",
        "--folder",
        dest="source",
        default=str(DEFAULT_SOURCE_ROOT),
        help="Root folder data. Default: data",
    )
    parser.add_argument("--marketplace", required=True, choices=sorted(SUPPORTED_MARKETPLACES))
    parser.add_argument("--phase", "--fase", dest="phase", required=True, choices=sorted(SUPPORTED_PHASES))
    parser.add_argument(
        "--report-dir",
        default="scripts/import_reports",
        help="Folder output manifest dry-run.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Insert data ke tabel raw staging. Tanpa flag ini script hanya dry-run.",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Nama database target. Default mengikuti IMPORT_DB_NAME/DB_NAME/.env.",
    )
    return parser.parse_args()


def load_file(item: MarketplaceFile, *, phase: str | None = None) -> list[LoadedFrame]:
    target_phase = phase or item.phase
    if item.marketplace == "lazada":
        loaded = lazada_loader.read_file(item.path, target_phase)
    elif item.marketplace == "shopee":
        loaded = shopee_loader.read_file(item.path, target_phase)
    elif item.marketplace == "tiktok_tokopedia":
        loaded = tiktok_tokopedia_loader.read_file(item.path, target_phase)
    else:
        raise NotImplementedError(f"Loader belum tersedia untuk marketplace: {item.marketplace}")

    if isinstance(loaded, list):
        return loaded
    return [loaded]


def write_manifest(
    rows: list[dict[str, object]],
    report_dir: str | Path,
    *,
    marketplace: str,
    phase: str,
) -> Path:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_path = output_dir / f"dry_run_{marketplace}_{phase}_{timestamp}.csv"

    fieldnames = [
        "status",
        "marketplace",
        "phase",
        "year",
        "month",
        "store_name",
        "start_date",
        "end_date",
        "table_name",
        "row_count",
        "inserted_rows",
        "column_count",
        "ignored_columns",
        "missing_columns",
        "sheet_name",
        "source_path",
        "error",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return output_path


def main():
    args = parse_args()
    engine = None
    append_to_table: Callable | None = None
    if args.execute:
        from scripts.database.connection import get_engine
        from scripts.database.staging import append_dataframe_to_table

        engine = get_engine(args.database)
        append_to_table = append_dataframe_to_table

    files = discover_files(args.source, marketplace=args.marketplace, phase=args.phase)
    if args.marketplace == "tiktok_tokopedia" and args.phase == "report":
        income_files = discover_files(args.source, marketplace=args.marketplace, phase="income")
        known_paths = {item.path for item in files}
        files.extend(item for item in income_files if item.path not in known_paths)
        files = sorted(files, key=lambda item: (item.marketplace, item.phase, str(item.path)))
    logger.info("Mode       : %s", "EXECUTE" if args.execute else "DRY-RUN")
    logger.info("Source     : %s", args.source)
    logger.info("Marketplace: %s", args.marketplace)
    logger.info("Phase      : %s", args.phase)
    logger.info("Total file : %s", len(files))

    rows: list[dict[str, object]] = []
    success_count = 0
    failed_count = 0
    total_inserted_rows = 0

    for index, item in enumerate(files, 1):
        logger.info("[%s/%s] %s", index, len(files), item.path)
        try:
            loaded_frames = load_file(item, phase=args.phase)
            success_count += 1
            for loaded in loaded_frames:
                if item.store_name and "store_name" in loaded.dataframe.columns:
                    loaded.dataframe["store_name"] = item.store_name

                inserted_rows = 0
                if engine is not None:
                    inserted_rows = append_to_table(
                        engine,
                        loaded.dataframe,
                        loaded.table_name,
                    )
                    total_inserted_rows += inserted_rows

                rows.append(
                    {
                        "status": "ok",
                        "marketplace": item.marketplace,
                        "phase": item.phase,
                        "year": item.year or "",
                        "month": item.month or "",
                        "store_name": item.store_name or "",
                        "start_date": item.start_date or "",
                        "end_date": item.end_date or "",
                        "table_name": loaded.table_name,
                        "row_count": loaded.row_count,
                        "inserted_rows": inserted_rows,
                        "column_count": len(loaded.dataframe.columns),
                        "ignored_columns": " | ".join(loaded.ignored_columns),
                        "missing_columns": " | ".join(loaded.missing_columns),
                        "sheet_name": loaded.sheet_name or "",
                        "source_path": str(item.path),
                        "error": "",
                    }
                )
        except Exception as exc:
            failed_count += 1
            logger.error("GAGAL: %s", exc)
            rows.append(
                {
                    "status": "error",
                    "marketplace": item.marketplace,
                    "phase": item.phase,
                    "year": item.year or "",
                    "month": item.month or "",
                    "store_name": item.store_name or "",
                    "start_date": item.start_date or "",
                    "end_date": item.end_date or "",
                    "table_name": "",
                    "row_count": 0,
                    "inserted_rows": 0,
                    "column_count": 0,
                    "ignored_columns": "",
                    "missing_columns": "",
                    "sheet_name": "",
                    "source_path": str(item.path),
                    "error": str(exc),
                }
            )

    manifest_path = write_manifest(
        rows,
        args.report_dir,
        marketplace=args.marketplace,
        phase=args.phase,
    )
    logger.info("-" * 60)
    logger.info(
        "%s selesai. Berhasil: %s | Gagal: %s",
        "Execute" if args.execute else "Dry-run",
        success_count,
        failed_count,
    )
    if args.execute:
        logger.info("Total rows inserted: %s", total_inserted_rows)
    logger.info("Manifest: %s", manifest_path)


if __name__ == "__main__":
    main()
