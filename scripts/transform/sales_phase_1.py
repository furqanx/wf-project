"""Transform sales order phase 1 into sales order facts."""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.file_discovery import MarketplaceFile, discover_files
from scripts.loaders import lazada as lazada_loader
from scripts.transform.audit import print_audit, run_audit, run_audit_on_connection
from scripts.transform.context import TransformContext


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
    parser.add_argument(
        "--source-folder",
        default=None,
        help=(
            "Read normalized staging files from folder instead of database staging table. "
            "For marketplace files, pass data/staging or data/staging/sales_online."
        ),
    )
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when store/product mappings are missing.",
    )
    return parser.parse_args()


def discover_order_files(source_folder: str | Path, source_system: str) -> list[MarketplaceFile]:
    source_root = Path(source_folder).expanduser().resolve()
    search_roots = []
    if (source_root / "sales_online").exists():
        search_roots.append(source_root / "sales_online")
    search_roots.append(source_root)

    for root in search_roots:
        files = discover_files(root, marketplace=source_system, phase="order")
        if files:
            return files

    raise FileNotFoundError(
        f"No {source_system} order files found under {source_root} "
        "or its sales_online subfolder."
    )


def load_lazada_order_folder(source_folder: str | Path) -> pd.DataFrame:
    files = discover_order_files(source_folder, "lazada")
    frames: list[pd.DataFrame] = []

    logger.info("Source mode : folder")
    logger.info("Source root : %s", Path(source_folder).expanduser().resolve())
    logger.info("Order files : %s", len(files))

    for index, item in enumerate(files, 1):
        logger.info("[%s/%s] Load %s", index, len(files), item.path)
        loaded = lazada_loader.read_order(item.path)
        df = loaded.dataframe.copy()
        if item.store_name and "store_name" in df.columns:
            df["store_name"] = item.store_name
        frames.append(df)

    if not frames:
        raise RuntimeError("No Lazada order rows loaded from source folder.")

    result = pd.concat(frames, ignore_index=True)
    logger.info("Loaded folder rows: %s", len(result))
    return result


def create_temp_staging_table(conn, *, source_system: str, source_folder: str | Path) -> str:
    if source_system != "lazada":
        raise NotImplementedError(
            f"Folder source mode is not implemented yet for source_system={source_system!r}."
        )

    df = load_lazada_order_folder(source_folder)
    table_name = "lazada_orders"
    df.to_sql(
        table_name,
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    logger.info("Temporary staging table created: pg_temp.%s rows=%s", table_name, len(df))
    return table_name


def main() -> None:
    args = parse_args()
    staging_schema = "pg_temp" if args.source_folder else args.staging_schema
    ctx = TransformContext(
        staging_schema=staging_schema,
        target_schema=args.target_schema,
    )
    engine = get_engine(args.database)

    sql_files = SOURCE_SQL_FILES[args.source_system]
    audit_sql = ctx.render_sql(sql_files["audit"])
    order_sql = ctx.render_sql(sql_files["order"])
    item_sql = ctx.render_sql(sql_files["item"])
    addon_sql = ctx.render_sql(sql_files["addon"]) if sql_files["addon"] else None

    if args.source_folder:
        with engine.begin() as conn:
            temp_table_name = create_temp_staging_table(
                conn,
                source_system=args.source_system,
                source_folder=args.source_folder,
            )
            try:
                logger.info("Run audit source_system=%s", args.source_system)
                audit = run_audit_on_connection(conn, audit_sql)
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
                order_result = conn.execute(text(order_sql))
                item_result = conn.execute(text(item_sql))
                addon_rows = 0
                if addon_sql:
                    addon_result = conn.execute(text(addon_sql))
                    addon_rows = addon_result.rowcount
            finally:
                conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{temp_table_name}"))
    else:
        logger.info("Source mode : database")
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
