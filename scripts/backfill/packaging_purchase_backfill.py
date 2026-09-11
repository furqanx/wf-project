"""Backfill packaging purchase fact."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.packaging_purchase import (
    build_source_df,
    run_packaging_purchase_transform,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-csv", required=True)
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when supplier/packaging mappings are missing.",
    )
    parser.add_argument("--export-unmapped-suppliers", default=None)
    parser.add_argument("--export-unmapped-items", default=None)
    parser.add_argument("--export-duplicate-grain", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("Packaging purchase CSV: %s", Path(args.source_csv).resolve())

    source_df = build_source_df(args.source_csv)
    logger.info("Loaded packaging purchase source rows: %s", len(source_df))

    engine = get_engine(args.database)
    with engine.begin() as conn:
        result = run_packaging_purchase_transform(
            conn,
            source_df=source_df,
            target_schema=args.target_schema,
            execute=args.execute,
            allow_unmapped=args.allow_unmapped,
            export_unmapped_suppliers=args.export_unmapped_suppliers,
            export_unmapped_items=args.export_unmapped_items,
            export_duplicate_grain=args.export_duplicate_grain,
        )

    logger.info(
        "Packaging purchase transform finished. packaging_purchase_rows=%s",
        result.packaging_purchase_rows,
    )


if __name__ == "__main__":
    main()
