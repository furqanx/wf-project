"""Transform marketplace income files into phase-2 settlement facts."""

from __future__ import annotations

import argparse
import csv
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
from scripts.loaders import shopee as shopee_loader
from scripts.loaders import tiktok_tokopedia as tiktok_tokopedia_loader
from scripts.transform.audit import print_audit, run_audit_on_connection
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
        "table": "shopee_income_main",
        "audit": "sales_settlement_shopee_audit.sql",
        "insert": "sales_settlement_shopee_insert.sql",
    },
    "lazada": {
        "table": "lazada_income",
        "audit": "sales_settlement_lazada_audit.sql",
        "insert": "sales_settlement_lazada_insert.sql",
    },
    "tiktok_tokopedia": {
        "table": "tiktok_tokopedia_income",
        "audit": "sales_settlement_tiktok_tokopedia_audit.sql",
        "insert": "sales_settlement_tiktok_tokopedia_insert.sql",
    },
}

SUPPORTED_SOURCES = set(SOURCE_SQL_FILES)
LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform marketplace income staging files into SSOT phase-2 settlement facts."
    )
    parser.add_argument("--source-system", required=True, choices=sorted(SUPPORTED_SOURCES))
    parser.add_argument("--target-schema", default="public")
    parser.add_argument(
        "--source-folder",
        default=str(PROJECT_ROOT / "data" / "staging"),
        help=(
            "Read normalized staging files from folder. Default: data/staging. "
            "Pass /opt/wf-project/data/staging on VPS."
        ),
    )
    parser.add_argument("--database", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert even when store mappings are missing.",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="Load only the first N discovered income files. Useful for quick dry-run testing.",
    )
    parser.add_argument(
        "--export-audit-rows",
        default=None,
        help="Optional CSV path for the audit metric output.",
    )
    return parser.parse_args()


def discover_income_files(
    source_folder: str | Path,
    source_system: str,
    *,
    limit_files: int | None = None,
) -> list[MarketplaceFile]:
    source_root = Path(source_folder).expanduser().resolve()
    search_roots = []
    if (source_root / "sales_online").exists():
        search_roots.append(source_root / "sales_online")
    search_roots.append(source_root)

    for root in search_roots:
        files = discover_files(root, marketplace=source_system, phase="income")
        if files:
            return files[:limit_files] if limit_files else files

    raise FileNotFoundError(
        f"No {source_system} income files found under {source_root} "
        "or its sales_online subfolder."
    )


def read_income_file(item: MarketplaceFile) -> list[pd.DataFrame]:
    if item.marketplace == "lazada":
        loaded = lazada_loader.read_income(item.path)
        frames = [loaded.dataframe.copy()]
    elif item.marketplace == "shopee":
        loaded_frames = shopee_loader.read_income(item.path)
        frames = [
            loaded.dataframe.copy()
            for loaded in loaded_frames
            if loaded.table_name == SOURCE_SQL_FILES["shopee"]["table"]
        ]
    elif item.marketplace == "tiktok_tokopedia":
        loaded = tiktok_tokopedia_loader.read_income(item.path)
        frames = [loaded.dataframe.copy()]
    else:
        raise NotImplementedError(f"Income loader is not implemented for {item.marketplace!r}.")

    for df in frames:
        if item.store_name and "store_name" in df.columns:
            df["store_name"] = item.store_name

    return frames


def load_income_folder(
    source_folder: str | Path,
    source_system: str,
    *,
    limit_files: int | None = None,
) -> pd.DataFrame:
    files = discover_income_files(source_folder, source_system, limit_files=limit_files)
    frames: list[pd.DataFrame] = []

    logger.info("Source mode : folder")
    logger.info("Source root : %s", Path(source_folder).expanduser().resolve())
    logger.info("Income files: %s", len(files))

    for index, item in enumerate(files, 1):
        logger.info("[%s/%s] Load %s", index, len(files), item.path)
        frames.extend(read_income_file(item))

    if not frames:
        raise RuntimeError(f"No {source_system} income rows loaded from source folder.")

    result = pd.concat(frames, ignore_index=True)
    logger.info("Loaded folder rows: %s", len(result))
    return result


def create_temp_staging_table(
    conn,
    *,
    source_system: str,
    source_folder: str | Path,
    limit_files: int | None = None,
) -> str:
    table_name = SOURCE_SQL_FILES[source_system]["table"]
    df = load_income_folder(source_folder, source_system, limit_files=limit_files)
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
    prepare_temp_staging_table(conn, source_system=source_system, table_name=table_name)
    return table_name


def configure_transaction_guardrails(conn, *, source_system: str) -> None:
    lock_key = f"sales_settlement_phase_2:{source_system}"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def prepare_temp_staging_table(conn, *, source_system: str, table_name: str) -> None:
    index_columns_by_source = {
        "lazada": ["nomor_pesanan", "id_pesanan", "sku_penjual", "store_name"],
        "shopee": ["no_pesanan", "store_name"],
        "tiktok_tokopedia": ["order_adjustment_id", "type", "store_name"],
    }

    for column in index_columns_by_source.get(source_system, []):
        conn.execute(text(f'CREATE INDEX ON pg_temp.{table_name} ("{column}")'))

    conn.execute(text(f"ANALYZE pg_temp.{table_name}"))
    logger.info("Temporary staging table indexed/analyzed: pg_temp.%s", table_name)


def write_audit_csv(rows: list[dict], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["metric", "value", "notes"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> None:
    args = parse_args()
    ctx = TransformContext(staging_schema="pg_temp", target_schema=args.target_schema)
    engine = get_engine(args.database)

    sql_files = SOURCE_SQL_FILES[args.source_system]
    audit_sql = ctx.render_sql(sql_files["audit"])
    insert_sql = ctx.render_sql(sql_files["insert"])

    with engine.begin() as conn:
        configure_transaction_guardrails(conn, source_system=args.source_system)
        temp_table_name = create_temp_staging_table(
            conn,
            source_system=args.source_system,
            source_folder=args.source_folder,
            limit_files=args.limit_files,
        )
        try:
            logger.info("Run audit source_system=%s", args.source_system)
            audit = run_audit_on_connection(conn, audit_sql)
            print_audit(audit)

            if args.export_audit_rows:
                output_path = write_audit_csv(audit.rows, args.export_audit_rows)
                logger.info("Audit export: %s", output_path)

            if audit.value("unmapped_store_rows") > 0 and not args.allow_unmapped:
                raise RuntimeError(
                    "Transform blocked: unmapped store rows detected. "
                    "Fix store mapping first, or rerun with --allow-unmapped for controlled testing."
                )

            if not args.execute:
                logger.info("Dry-run only. Add --execute to insert into target facts.")
                return

            logger.info("Execute transform source_system=%s", args.source_system)
            logger.info("Insert settlement rows")
            result = conn.execute(text(insert_sql))
            logger.info("Insert settlement rows done: %s", result.rowcount)
            conn.execute(text(f"ANALYZE {args.target_schema}.fact_sales_settlement"))
        finally:
            conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{temp_table_name}"))

    logger.info("Transform finished. settlement_rows=%s", result.rowcount)


if __name__ == "__main__":
    main()
