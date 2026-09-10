"""Backfill production output CSV into fact_production_output."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.production_output import (
    read_production_csv,
    run_production_output_transform,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-csv",
        required=True,
        help="Path to latest Hasan production CSV.",
    )
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when product mappings are missing.",
    )
    parser.add_argument(
        "--export-unmapped-products",
        default=None,
        help="Optional CSV path for unmapped production products.",
    )
    parser.add_argument(
        "--export-duplicate-grain",
        default=None,
        help="Optional CSV path for apparent duplicate date/product/from/box rows.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_csv = Path(args.source_csv).expanduser().resolve()
    logger.info("Production source CSV: %s", source_csv)

    source_df = read_production_csv(source_csv)
    logger.info("Loaded production source rows: %s", len(source_df))

    engine = get_engine(args.database)
    with engine.begin() as conn:
        result = run_production_output_transform(
            conn,
            source_df=source_df,
            target_schema=args.target_schema,
            execute=args.execute,
            allow_unmapped=args.allow_unmapped,
            export_unmapped_products=args.export_unmapped_products,
            export_duplicate_grain=args.export_duplicate_grain,
        )

    logger.info(
        "Production output transform finished. production_output_rows=%s",
        result.production_output_rows,
    )


if __name__ == "__main__":
    main()
