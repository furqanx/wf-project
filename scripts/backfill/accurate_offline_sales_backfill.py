"""Backfill Accurate offline sales audit CSVs into phase-1 sales facts."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.accurate_offline_sales import (
    read_csv,
    run_accurate_offline_sales_transform,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Accurate offline sales receipt/invoice audit CSVs into phase-1 facts."
    )
    parser.add_argument("--receipt-csv", required=True)
    parser.add_argument("--invoice-csv", required=True)
    parser.add_argument("--item-csv", required=True)
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when product mapping or source link issues are present.",
    )
    parser.add_argument(
        "--export-unmapped-products",
        default=None,
        help="Optional CSV path for Accurate item rows that do not resolve to product_sku_alias.",
    )
    parser.add_argument(
        "--export-duplicate-grain",
        default=None,
        help="Optional CSV path for duplicate invoice/item grain rows.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    receipt_csv = Path(args.receipt_csv).expanduser().resolve()
    invoice_csv = Path(args.invoice_csv).expanduser().resolve()
    item_csv = Path(args.item_csv).expanduser().resolve()

    logger.info("Accurate sales receipt CSV: %s", receipt_csv)
    logger.info("Accurate sales invoice CSV: %s", invoice_csv)
    logger.info("Accurate sales item CSV   : %s", item_csv)

    receipt_df = read_csv(receipt_csv)
    invoice_df = read_csv(invoice_csv)
    item_df = read_csv(item_csv)

    engine = get_engine(args.database)
    with engine.begin() as conn:
        result = run_accurate_offline_sales_transform(
            conn,
            receipt_df=receipt_df,
            invoice_df=invoice_df,
            item_df=item_df,
            target_schema=args.target_schema,
            execute=args.execute,
            allow_unmapped=args.allow_unmapped,
            export_unmapped_products=args.export_unmapped_products,
            export_duplicate_grain=args.export_duplicate_grain,
        )

    logger.info(
        "Accurate offline sales transform finished. order_rows=%s item_rows=%s",
        result.order_rows,
        result.item_rows,
    )


if __name__ == "__main__":
    main()
