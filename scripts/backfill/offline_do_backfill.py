"""Backfill legacy offline DO CSVs into phase-1 sales facts."""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.offline_sales import read_legacy_do_csv, run_offline_do_transform


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

warnings.filterwarnings(
    "ignore",
    message="Workbook contains no default style, apply openpyxl's default",
    category=UserWarning,
    module="openpyxl.styles.stylesheet",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill legacy offline DO header/item CSVs into phase-1 sales facts."
    )
    parser.add_argument(
        "--header-csv",
        default=str(PROJECT_ROOT / "fact_do_header.csv"),
        help="Path to legacy fact_do_header.csv.",
    )
    parser.add_argument(
        "--item-csv",
        default=str(PROJECT_ROOT / "fact_do_item.csv"),
        help="Path to legacy fact_do_item.csv.",
    )
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when partner/product mappings are missing.",
    )
    parser.add_argument(
        "--export-unmapped-products",
        default=None,
        help="Optional CSV path for top unmapped offline product/SKU rows.",
    )
    parser.add_argument(
        "--export-unmapped-partners",
        default=None,
        help="Optional CSV path for top unmapped offline B2B partner rows.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    header_csv = Path(args.header_csv).expanduser().resolve()
    item_csv = Path(args.item_csv).expanduser().resolve()

    logger.info("Offline DO header CSV: %s", header_csv)
    logger.info("Offline DO item CSV  : %s", item_csv)

    header_df = read_legacy_do_csv(header_csv)
    item_df = read_legacy_do_csv(item_csv)

    engine = get_engine(args.database)
    with engine.begin() as conn:
        result = run_offline_do_transform(
            conn,
            header_df=header_df,
            item_df=item_df,
            target_schema=args.target_schema,
            execute=args.execute,
            allow_unmapped=args.allow_unmapped,
            export_unmapped_products=args.export_unmapped_products,
            export_unmapped_partners=args.export_unmapped_partners,
        )

    logger.info(
        "Offline DO transform finished. order_rows=%s item_rows=%s",
        result.order_rows,
        result.item_rows,
    )


if __name__ == "__main__":
    main()
