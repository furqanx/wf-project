"""Transform sales order phase 1 into sales order facts."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.audit import print_audit, run_audit
from scripts.transform.context import TransformContext


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


SOURCE_SQL_FILES = {
    "shopee": {
        "audit": "sales_order_shopee_audit.sql",
        "order": "sales_order_shopee_insert.sql",
        "item": "sales_order_item_shopee_insert.sql",
        "addon": "sales_order_addon_shopee_insert.sql",
    },
    "lazada": {
        "audit": "sales_order_lazada_audit.sql",
        "order": "sales_order_lazada_insert.sql",
        "item": "sales_order_item_lazada_insert.sql",
        "addon": None,
    },
}

SUPPORTED_SOURCES = set(SOURCE_SQL_FILES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform staging sales order data into SSOT phase-1 sales facts."
    )
    parser.add_argument("--source-system", required=True, choices=sorted(SUPPORTED_SOURCES))
    parser.add_argument("--staging-schema", default="public_staging")
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when store/product mappings are missing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ctx = TransformContext(
        staging_schema=args.staging_schema,
        target_schema=args.target_schema,
    )
    engine = get_engine(args.database)

    sql_files = SOURCE_SQL_FILES[args.source_system]
    audit_sql = ctx.render_sql(sql_files["audit"])
    order_sql = ctx.render_sql(sql_files["order"])
    item_sql = ctx.render_sql(sql_files["item"])
    addon_sql = ctx.render_sql(sql_files["addon"]) if sql_files["addon"] else None

    logger.info("Run audit source_system=%s", args.source_system)
    audit = run_audit(engine, audit_sql)
    print_audit(audit)

    if not args.execute:
        logger.info("Dry-run only. Add --execute to insert into target facts.")
        return

    if audit.has_blocking_issues() and not args.allow_unmapped:
        raise RuntimeError(
            "Transform blocked: unmapped store/product rows detected. "
            "Fix mappings first, or rerun with --allow-unmapped for controlled testing."
        )

    logger.info("Execute transform source_system=%s", args.source_system)
    with engine.begin() as conn:
        order_result = conn.execute(text(order_sql))
        item_result = conn.execute(text(item_sql))
        addon_rows = 0
        if addon_sql:
            addon_result = conn.execute(text(addon_sql))
            addon_rows = addon_result.rowcount

    logger.info(
        "Transform finished. order_rows=%s item_rows=%s addon_rows=%s",
        order_result.rowcount,
        item_result.rowcount,
        addon_rows,
    )


if __name__ == "__main__":
    main()
