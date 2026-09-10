"""Backfill monthly and daily production targets into fact_production_target."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.production_target import (
    build_source_df,
    run_production_target_transform,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monthly-target-csv", required=True)
    parser.add_argument("--daily-target-csv", required=True)
    parser.add_argument(
        "--production-source-csv",
        required=True,
        help="Latest Hasan production CSV used to infer legacy product ID to SKU mapping.",
    )
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when product mappings are missing.",
    )
    parser.add_argument("--export-unmapped-products", default=None)
    parser.add_argument("--export-duplicate-grain", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("Monthly production target CSV: %s", Path(args.monthly_target_csv).resolve())
    logger.info("Daily production target CSV  : %s", Path(args.daily_target_csv).resolve())
    logger.info("Production source CSV       : %s", Path(args.production_source_csv).resolve())

    source_df = build_source_df(
        monthly_target_csv=args.monthly_target_csv,
        daily_target_csv=args.daily_target_csv,
        production_source_csv=args.production_source_csv,
    )
    logger.info("Loaded production target source rows: %s", len(source_df))

    engine = get_engine(args.database)
    with engine.begin() as conn:
        result = run_production_target_transform(
            conn,
            source_df=source_df,
            target_schema=args.target_schema,
            execute=args.execute,
            allow_unmapped=args.allow_unmapped,
            export_unmapped_products=args.export_unmapped_products,
            export_duplicate_grain=args.export_duplicate_grain,
        )

    logger.info(
        "Production target transform finished. production_target_rows=%s",
        result.production_target_rows,
    )


if __name__ == "__main__":
    main()
