"""Transform marketplace report files into phase-5 balance transaction facts."""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import warnings
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

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
from scripts.loaders.common import LoadedFrame
from scripts.transform.audit import AuditResult, print_audit, run_audit_on_connection
from scripts.transform.context import TransformContext
from scripts.transform.sales_fee_detail_phase_3 import (
    amount_sign,
    batch_export_path,
    chunked,
    clean_text,
    make_raw_record_id,
    normalize_name,
    parse_decimal,
)


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

SUPPORTED_SOURCES = {"lazada", "shopee", "tiktok_tokopedia"}
LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"

TEMP_BALANCE_TABLE = "sales_balance_transaction_source"
TEMP_BALANCE_COLUMNS = [
    "balance_source_sequence",
    "source_system",
    "source_table",
    "store_name",
    "normalized_store_name",
    "external_transaction_id",
    "external_order_id",
    "transaction_type",
    "transaction_sub_type",
    "transaction_status",
    "transaction_description",
    "transaction_description_key",
    "movement_direction",
    "raw_amount",
    "signed_amount",
    "amount_sign_from_source",
    "balance_after_amount",
    "currency_code",
    "transaction_occurred_at_text",
    "transaction_requested_at_text",
    "transaction_succeeded_at_text",
    "bank_account",
    "source_file",
    "source_sheet",
    "source_row_number",
    "raw_record_id",
]


@dataclass(frozen=True)
class ExtractionStats:
    report_files: int
    loaded_report_rows: int = 0
    extracted_balance_rows: int = 0
    skipped_missing_amount_rows: int = 0
    zero_amount_rows: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "report_files": self.report_files,
            "loaded_report_rows": self.loaded_report_rows,
            "extracted_balance_rows": self.extracted_balance_rows,
            "skipped_missing_amount_rows": self.skipped_missing_amount_rows,
            "zero_amount_rows": self.zero_amount_rows,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform marketplace report files into SSOT sales phase-5 balance facts."
    )
    parser.add_argument("--source-system", required=True, choices=sorted(SUPPORTED_SOURCES))
    parser.add_argument("--source-folder", default=str(PROJECT_ROOT / "data" / "staging"))
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--limit-files", type=int, default=None)
    parser.add_argument("--export-audit", default=None)
    parser.add_argument(
        "--insert-batch-size",
        type=int,
        default=50_000,
        help="Number of extracted balance rows to insert per SQL batch during execute.",
    )
    parser.add_argument(
        "--file-batch-size",
        type=int,
        default=None,
        help="Number of report files loaded per cycle.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped-store",
        action="store_true",
        help="Allow insert even when some balance rows do not resolve to dim_store.",
    )
    return parser.parse_args()


def normalize_value(value: Any) -> str | None:
    text_value = clean_text(value)
    if text_value is None:
        return None
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text_value).strip("_").lower()
    return normalized or None


def description_key(value: Any) -> str | None:
    normalized = normalize_value(value)
    return normalized[:120] if normalized else None


def discover_report_files(
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
        files = discover_files(root, marketplace=source_system, phase="report")
        if files:
            return files[:limit_files] if limit_files else files

    raise FileNotFoundError(
        f"No {source_system} report files found under {source_root} "
        "or its sales_online subfolder."
    )


def read_report_file(item: MarketplaceFile) -> LoadedFrame:
    if item.marketplace == "lazada":
        return lazada_loader.read_report(item.path)
    if item.marketplace == "shopee":
        return shopee_loader.read_report(item.path)
    if item.marketplace == "tiktok_tokopedia":
        return tiktok_tokopedia_loader.read_report(item.path)
    raise NotImplementedError(f"Report loader is not implemented for {item.marketplace!r}.")


def raw_amount(source_system: str, row: pd.Series) -> Decimal | None:
    if source_system == "shopee":
        return parse_decimal(row.get("jumlah"))
    return parse_decimal(row.get("amount"))


def balance_after_amount(source_system: str, row: pd.Series) -> Decimal | None:
    if source_system == "shopee":
        return parse_decimal(row.get("saldo_akhir"))
    return None


def movement_direction(amount: Decimal) -> str:
    if amount > 0:
        return "credit"
    if amount < 0:
        return "debit"
    return "zero"


def source_transaction_fields(source_system: str, row: pd.Series) -> tuple[str, str | None, str | None, str | None]:
    if source_system == "lazada":
        return (
            clean_text(row.get("type")) or "unspecified",
            clean_text(row.get("sub_type")),
            None,
            clean_text(row.get("remarks")),
        )
    if source_system == "shopee":
        return (
            clean_text(row.get("tipe_transaksi")) or "unspecified",
            clean_text(row.get("jenis_transaksi")),
            clean_text(row.get("status")),
            clean_text(row.get("deskripsi")),
        )
    if source_system == "tiktok_tokopedia":
        return (
            clean_text(row.get("type")) or "unspecified",
            None,
            clean_text(row.get("status")),
            None,
        )
    return ("unspecified", None, None, None)


def external_transaction_id(source_system: str, row: pd.Series) -> str | None:
    if source_system == "lazada":
        return clean_text(row.get("transaction_number"))
    if source_system == "tiktok_tokopedia":
        return clean_text(row.get("reference_id"))
    return None


def external_order_id(source_system: str, row: pd.Series) -> str | None:
    if source_system == "shopee":
        return clean_text(row.get("no_pesanan"))
    return None


def transaction_occurred_at_text(source_system: str, row: pd.Series) -> str | None:
    if source_system == "lazada":
        return clean_text(row.get("transaction_time"))
    if source_system == "shopee":
        return clean_text(row.get("tanggal_transaksi"))
    if source_system == "tiktok_tokopedia":
        return clean_text(row.get("success_time")) or clean_text(row.get("request_time"))
    return None


def transaction_requested_at_text(source_system: str, row: pd.Series) -> str | None:
    if source_system == "tiktok_tokopedia":
        return clean_text(row.get("request_time"))
    return None


def transaction_succeeded_at_text(source_system: str, row: pd.Series) -> str | None:
    if source_system == "tiktok_tokopedia":
        return clean_text(row.get("success_time"))
    if source_system == "shopee":
        status = normalize_value(row.get("status"))
        if status == "transaksi_selesai":
            return clean_text(row.get("tanggal_transaksi"))
    return None


def currency_code(source_system: str) -> str:
    return "IDR"


def bank_account(source_system: str, row: pd.Series) -> str | None:
    if source_system == "tiktok_tokopedia":
        return clean_text(row.get("bank_account"))
    return None


def build_balance_row(
    *,
    source_system: str,
    store_name: str | None,
    loaded: LoadedFrame,
    row_number: int,
    row: pd.Series,
) -> dict[str, Any] | None:
    amount = raw_amount(source_system, row)
    if amount is None:
        return None

    transaction_type, transaction_sub_type, transaction_status, transaction_description = source_transaction_fields(
        source_system,
        row,
    )
    ext_transaction_id = external_transaction_id(source_system, row)
    ext_order_id = external_order_id(source_system, row)
    balance_after = balance_after_amount(source_system, row)
    raw_record_id = make_raw_record_id(
        [
            source_system,
            loaded.table_name,
            store_name,
            ext_transaction_id,
            ext_order_id,
            transaction_type,
            transaction_sub_type,
            transaction_status,
            transaction_description,
            amount,
            balance_after,
            loaded.source_path.name,
            loaded.sheet_name,
            row_number,
        ]
    )

    return {
        "source_system": source_system,
        "source_table": loaded.table_name,
        "store_name": store_name,
        "normalized_store_name": normalize_name(store_name),
        "external_transaction_id": ext_transaction_id,
        "external_order_id": ext_order_id,
        "transaction_type": transaction_type,
        "transaction_sub_type": transaction_sub_type,
        "transaction_status": transaction_status,
        "transaction_description": transaction_description,
        "transaction_description_key": description_key(transaction_description),
        "movement_direction": movement_direction(amount),
        "raw_amount": amount,
        "signed_amount": amount,
        "amount_sign_from_source": amount_sign(amount),
        "balance_after_amount": balance_after,
        "currency_code": currency_code(source_system),
        "transaction_occurred_at_text": transaction_occurred_at_text(source_system, row),
        "transaction_requested_at_text": transaction_requested_at_text(source_system, row),
        "transaction_succeeded_at_text": transaction_succeeded_at_text(source_system, row),
        "bank_account": bank_account(source_system, row),
        "source_file": loaded.source_path.name,
        "source_sheet": loaded.sheet_name,
        "source_row_number": row_number,
        "raw_record_id": raw_record_id,
    }


def load_balance_source_dataframe_from_files(
    *,
    files: list[MarketplaceFile],
    source_folder: str | Path,
    source_system: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    all_rows: list[dict[str, Any]] = []
    totals = ExtractionStats(report_files=len(files)).as_dict()

    logger.info("Source mode : folder")
    logger.info("Source root : %s", Path(source_folder).expanduser().resolve())
    logger.info("Report files: %s", len(files))

    for index, item in enumerate(files, 1):
        logger.info("[%s/%s] Load %s", index, len(files), item.path)
        loaded = read_report_file(item)
        df = loaded.dataframe.copy()
        if item.store_name and "store_name" in df.columns:
            df["store_name"] = item.store_name
        loaded = LoadedFrame(
            table_name=loaded.table_name,
            dataframe=df,
            source_path=loaded.source_path,
            sheet_name=loaded.sheet_name,
            ignored_columns=loaded.ignored_columns,
            missing_columns=loaded.missing_columns,
        )
        totals["loaded_report_rows"] += len(df)

        for row_index, row in df.iterrows():
            row_number = int(row_index) + 1
            balance_row = build_balance_row(
                source_system=source_system,
                store_name=item.store_name,
                loaded=loaded,
                row_number=row_number,
                row=row,
            )
            if balance_row is None:
                totals["skipped_missing_amount_rows"] += 1
                continue
            if balance_row["amount_sign_from_source"] == 0:
                totals["zero_amount_rows"] += 1
            all_rows.append(balance_row)

    balance_df = pd.DataFrame(all_rows, columns=TEMP_BALANCE_COLUMNS)
    if not balance_df.empty:
        balance_df["balance_source_sequence"] = range(1, len(balance_df) + 1)
    totals["extracted_balance_rows"] = len(balance_df)
    logger.info("Loaded report rows: %s", totals["loaded_report_rows"])
    logger.info("Extracted balance rows: %s", len(balance_df))
    return balance_df, totals


def create_temp_balance_source_table(conn, df: pd.DataFrame) -> None:
    insert_df = df.copy()
    for column in ["raw_amount", "signed_amount", "balance_after_amount"]:
        if column in insert_df.columns:
            insert_df[column] = insert_df[column].map(lambda value: None if pd.isna(value) else str(value))

    insert_df.to_sql(
        TEMP_BALANCE_TABLE,
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    logger.info(
        "Temporary balance source table created: pg_temp.%s rows=%s",
        TEMP_BALANCE_TABLE,
        len(insert_df),
    )

    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_BALANCE_TABLE} ("source_system")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_BALANCE_TABLE} ("balance_source_sequence")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_BALANCE_TABLE} ("normalized_store_name")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_BALANCE_TABLE} ("external_transaction_id")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_BALANCE_TABLE} ("external_order_id")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_BALANCE_TABLE} ("raw_record_id")'))
    conn.execute(text(f"ANALYZE pg_temp.{TEMP_BALANCE_TABLE}"))
    logger.info("Temporary balance source table indexed/analyzed: pg_temp.%s", TEMP_BALANCE_TABLE)


def configure_transaction_guardrails(conn, *, source_system: str) -> None:
    lock_key = f"sales_balance_phase_5:{source_system}"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def write_audit_csv(audit: AuditResult, extraction_stats: dict[str, int], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value", "notes"])
        for row in audit.rows:
            writer.writerow([row.get("metric"), row.get("value"), row.get("notes") or ""])
        for metric, value in extraction_stats.items():
            writer.writerow([metric, value, "Python extraction statistic before temp table insert."])
    return path


def main() -> None:
    args = parse_args()
    ctx = TransformContext(staging_schema="pg_temp", target_schema=args.target_schema)
    audit_sql = ctx.render_sql("sales_balance_transaction_audit.sql")
    insert_sql = ctx.render_sql("sales_balance_transaction_insert.sql")
    engine = get_engine(args.database)
    inserted_rows = 0
    total_balance_rows = 0

    files = discover_report_files(
        args.source_folder,
        args.source_system,
        limit_files=args.limit_files,
    )
    file_batches = chunked(files, args.file_batch_size)
    logger.info("File batches: %s batch_size=%s", len(file_batches), args.file_batch_size or "all")

    with engine.connect() as conn:
        for batch_index, batch_files in enumerate(file_batches, 1):
            logger.info(
                "Process file batch %s/%s files=%s",
                batch_index,
                len(file_batches),
                len(batch_files),
            )
            balance_df, extraction_stats = load_balance_source_dataframe_from_files(
                files=batch_files,
                source_folder=args.source_folder,
                source_system=args.source_system,
            )
            total_balance_rows += len(balance_df)

            try:
                with conn.begin():
                    configure_transaction_guardrails(conn, source_system=args.source_system)
                    create_temp_balance_source_table(conn, balance_df)

                    logger.info("Run audit source_system=%s", args.source_system)
                    audit = run_audit_on_connection(conn, audit_sql)
                    print_audit(audit)
                    for metric, value in extraction_stats.items():
                        print(f"{metric},{value},Python extraction statistic before temp table insert.")

                    audit_export_path = batch_export_path(
                        args.export_audit,
                        batch_index,
                        len(file_batches),
                    )
                    if audit_export_path:
                        output_path = write_audit_csv(audit, extraction_stats, audit_export_path)
                        logger.info("Audit export: %s", output_path)

                if not args.execute:
                    logger.info("Dry-run file batch only. Add --execute to insert into target facts.")
                    continue

                if audit.value("unmapped_store_rows") > 0 and not args.allow_unmapped_store:
                    raise RuntimeError(
                        "Transform blocked: balance rows with unmapped stores detected. "
                        "Fix store mappings or rerun with --allow-unmapped-store for controlled testing."
                    )

                logger.info("Execute transform source_system=%s", args.source_system)
                logger.info("Insert balance transaction rows batch_size=%s", args.insert_batch_size)
                source_balance_rows = len(balance_df)
                for row_batch_start in range(1, source_balance_rows + 1, args.insert_batch_size):
                    row_batch_end = min(row_batch_start + args.insert_batch_size, source_balance_rows + 1)
                    with conn.begin():
                        configure_transaction_guardrails(conn, source_system=args.source_system)
                        result = conn.execute(
                            text(insert_sql),
                            {"batch_start": row_batch_start, "batch_end": row_batch_end},
                        )
                    inserted_rows += max(result.rowcount or 0, 0)
                    logger.info(
                        "Insert balance transaction batch done: file_batch=%s row_start=%s row_end=%s rows=%s total_inserted=%s",
                        batch_index,
                        row_batch_start,
                        row_batch_end - 1,
                        result.rowcount,
                        inserted_rows,
                    )
            finally:
                try:
                    if not conn.closed:
                        with conn.begin():
                            conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{TEMP_BALANCE_TABLE}"))
                except Exception as exc:
                    logger.warning("Could not drop temp table after file batch: %s", exc)

        if args.execute:
            with conn.begin():
                configure_transaction_guardrails(conn, source_system=args.source_system)
                conn.execute(text(f"ANALYZE {args.target_schema}.fact_balance_transaction"))

    logger.info(
        "Transform finished. source_balance_rows=%s balance_transaction_rows=%s",
        total_balance_rows,
        inserted_rows,
    )


if __name__ == "__main__":
    main()
