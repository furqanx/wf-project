"""Backfill raw material purchase header/detail facts."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.raw_material_purchase import (
    build_source_tables,
    run_raw_material_purchase_transform,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-header-csv", default=None)
    parser.add_argument("--legacy-item-csv", default=None)
    parser.add_argument("--latest-source-csv", default=None)
    parser.add_argument("--latest-cutoff-date", default="2026-04-25")
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when supplier/material mappings are missing.",
    )
    parser.add_argument("--export-unmapped-suppliers", default=None)
    parser.add_argument("--export-unmapped-items", default=None)
    parser.add_argument("--export-duplicate-grain", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.legacy_header_csv:
        logger.info("Legacy raw material header CSV: %s", Path(args.legacy_header_csv).resolve())
    if args.legacy_item_csv:
        logger.info("Legacy raw material item CSV  : %s", Path(args.legacy_item_csv).resolve())
    if args.latest_source_csv:
        logger.info("Latest raw material source CSV: %s", Path(args.latest_source_csv).resolve())
        logger.info("Latest cutoff date            : %s", args.latest_cutoff_date)

    source = build_source_tables(
        legacy_header_csv=args.legacy_header_csv,
        legacy_item_csv=args.legacy_item_csv,
        latest_source_csv=args.latest_source_csv,
        latest_cutoff_date=args.latest_cutoff_date,
    )
    logger.info(
        "Loaded raw material source rows: header_rows=%s item_rows=%s",
        len(source.header_df),
        len(source.item_df),
    )

    engine = get_engine(args.database)
    with engine.begin() as conn:
        result = run_raw_material_purchase_transform(
            conn,
            source=source,
            target_schema=args.target_schema,
            execute=args.execute,
            allow_unmapped=args.allow_unmapped,
            export_unmapped_suppliers=args.export_unmapped_suppliers,
            export_unmapped_items=args.export_unmapped_items,
            export_duplicate_grain=args.export_duplicate_grain,
        )

    logger.info(
        "Raw material purchase transform finished. purchase_rows=%s purchase_item_rows=%s",
        result.purchase_rows,
        result.purchase_item_rows,
    )


if __name__ == "__main__":
    main()
