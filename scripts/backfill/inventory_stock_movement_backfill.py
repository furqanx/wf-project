"""Backfill inventory stock movement fact from legacy fact_stock_out export."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.inventory_stock_movement import (
    build_source_df,
    run_inventory_stock_movement_transform,
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
        help="Allow insert even when product or b2b partner mappings are missing.",
    )
    parser.add_argument("--export-unmapped-products", default=None)
    parser.add_argument("--export-unmapped-partners", default=None)
    parser.add_argument("--export-duplicate-grain", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("Inventory stock movement CSV: %s", Path(args.source_csv).resolve())

    source_df = build_source_df(args.source_csv)
    logger.info("Loaded inventory stock movement source rows: %s", len(source_df))

    engine = get_engine(args.database)
    with engine.begin() as conn:
        result = run_inventory_stock_movement_transform(
            conn,
            source_df=source_df,
            target_schema=args.target_schema,
            execute=args.execute,
            allow_unmapped=args.allow_unmapped,
            export_unmapped_products=args.export_unmapped_products,
            export_unmapped_partners=args.export_unmapped_partners,
            export_duplicate_grain=args.export_duplicate_grain,
        )

    logger.info(
        "Inventory stock movement transform finished. inventory_stock_movement_rows=%s",
        result.inventory_stock_movement_rows,
    )


if __name__ == "__main__":
    main()
