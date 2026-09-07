"""Transform marketplace income adjustments into sales settlement adjustment facts."""

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

from scripts.audit.marketplace_adjustment_candidates import ADJUSTMENT_KEYWORD_RE
from scripts.database.connection import get_engine
from scripts.file_discovery import MarketplaceFile
from scripts.loaders.common import LoadedFrame
from scripts.transform.audit import AuditResult, print_audit, run_audit_on_connection
from scripts.transform.context import TransformContext
from scripts.transform.sales_fee_detail_phase_3 import (
    FeeAlias,
    amount_sign,
    apply_sign_rule,
    batch_export_path,
    chunked,
    clean_text,
    discover_income_files,
    fetch_fee_aliases,
    make_raw_record_id,
    normalize_name,
    parse_decimal,
    read_income_file,
    sign_confidence,
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

SUPPORTED_SOURCES = {"tiktok_tokopedia"}
LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"

TEMP_ADJUSTMENT_TABLE = "sales_settlement_adjustment_source"
TEMP_ADJUSTMENT_COLUMNS = [
    "adjustment_source_sequence",
    "source_system",
    "source_table",
    "store_name",
    "normalized_store_name",
    "external_adjustment_id",
    "related_external_order_id",
    "raw_transaction_type",
    "fee_type_id",
    "raw_adjustment_name",
    "raw_adjustment_amount",
    "signed_adjustment_amount",
    "amount_sign_from_source",
    "sign_rule",
    "sign_confidence",
    "review_status",
    "currency_code",
    "adjustment_occurred_at_text",
    "source_file",
    "source_sheet",
    "source_row_number",
    "raw_record_id",
]

NON_ORDER_TRANSACTION_TYPES = {"order", "pesanan"}


@dataclass(frozen=True)
class ExtractionStats:
    income_files: int
    loaded_income_rows: int = 0
    skipped_zero_adjustment_values: int = 0
    skipped_missing_adjustment_values: int = 0
    skipped_review_adjustment_values: int = 0
    skipped_without_adjustment_id: int = 0
    skipped_out_of_scope_rows: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "income_files": self.income_files,
            "loaded_income_rows": self.loaded_income_rows,
            "skipped_zero_adjustment_values": self.skipped_zero_adjustment_values,
            "skipped_missing_adjustment_values": self.skipped_missing_adjustment_values,
            "skipped_review_adjustment_values": self.skipped_review_adjustment_values,
            "skipped_without_adjustment_id": self.skipped_without_adjustment_id,
            "skipped_out_of_scope_rows": self.skipped_out_of_scope_rows,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform marketplace income adjustment candidates into SSOT sales phase-4 fact."
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
        help="Number of extracted adjustment rows to insert per SQL batch during execute.",
    )
    parser.add_argument(
        "--file-batch-size",
        type=int,
        default=None,
        help="Number of income files loaded per cycle.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-review-adjustments",
        action="store_true",
        help="Include fee_type rows whose sign_rule/review_status still requires manual review.",
    )
    parser.add_argument(
        "--allow-unmapped-store",
        action="store_true",
        help="Allow insert even when some adjustment rows do not resolve to dim_store.",
    )
    return parser.parse_args()


def normalize_transaction_type(value: Any) -> str:
    text_value = clean_text(value)
    if text_value is None:
        return "unspecified"
    return re.sub(r"[^a-zA-Z0-9]+", "_", text_value).strip("_").lower() or "unspecified"


def is_phase4_alias(alias: FeeAlias) -> bool:
    searchable = " ".join(
        [
            alias.source_table,
            alias.raw_fee_name,
            alias.normalized_fee_name,
            alias.mapped_column,
            alias.amount_column,
        ]
    )
    return bool(ADJUSTMENT_KEYWORD_RE.search(searchable))


def is_phase4_income_row(source_system: str, row: pd.Series) -> bool:
    if source_system != "tiktok_tokopedia":
        return False
    return normalize_transaction_type(row.get("type")) not in NON_ORDER_TRANSACTION_TYPES


def build_adjustment_row(
    *,
    source_system: str,
    source_table: str,
    store_name: str | None,
    loaded: LoadedFrame,
    row_number: int,
    row: pd.Series,
    alias: FeeAlias,
    raw_amount: Decimal,
) -> dict[str, Any] | None:
    external_adjustment_id = clean_text(row.get("order_adjustment_id"))
    if not external_adjustment_id:
        return None

    transaction_type = normalize_transaction_type(row.get("type"))
    related_external_order_id = clean_text(row.get("related_order_id"))
    raw_transaction_type = clean_text(row.get("type")) or transaction_type
    signed_amount = apply_sign_rule(raw_amount, alias.sign_rule)
    confidence = sign_confidence(alias.sign_rule, alias.review_status)
    raw_record_id = make_raw_record_id(
        [
            source_system,
            source_table,
            store_name,
            external_adjustment_id,
            related_external_order_id,
            transaction_type,
            alias.fee_type_id,
            alias.raw_fee_name,
            loaded.source_path.name,
            loaded.sheet_name,
            row_number,
        ]
    )

    return {
        "source_system": source_system,
        "source_table": source_table,
        "store_name": store_name,
        "normalized_store_name": normalize_name(store_name),
        "external_adjustment_id": external_adjustment_id,
        "related_external_order_id": related_external_order_id,
        "raw_transaction_type": raw_transaction_type,
        "fee_type_id": alias.fee_type_id,
        "raw_adjustment_name": alias.raw_fee_name,
        "raw_adjustment_amount": raw_amount,
        "signed_adjustment_amount": signed_amount,
        "amount_sign_from_source": amount_sign(raw_amount),
        "sign_rule": alias.sign_rule,
        "sign_confidence": confidence,
        "review_status": alias.review_status,
        "currency_code": clean_text(row.get("currency")) or "IDR",
        "adjustment_occurred_at_text": clean_text(row.get("order_settled_time"))
        or clean_text(row.get("order_created_time")),
        "source_file": loaded.source_path.name,
        "source_sheet": loaded.sheet_name,
        "source_row_number": row_number,
        "raw_record_id": raw_record_id,
    }


def extract_frame_adjustment_rows(
    *,
    source_system: str,
    loaded: LoadedFrame,
    store_name: str | None,
    aliases: list[FeeAlias],
    allow_review_adjustments: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    stats = {
        "skipped_zero_adjustment_values": 0,
        "skipped_missing_adjustment_values": 0,
        "skipped_review_adjustment_values": 0,
        "skipped_without_adjustment_id": 0,
        "skipped_out_of_scope_rows": 0,
    }
    aliases_by_table = [
        alias
        for alias in aliases
        if alias.source_table == loaded.table_name
        and alias.fee_source_kind == "column_fee"
        and is_phase4_alias(alias)
    ]
    if not aliases_by_table:
        return rows, stats

    for index, row in loaded.dataframe.iterrows():
        row_number = int(index) + 1
        if not is_phase4_income_row(source_system, row):
            stats["skipped_out_of_scope_rows"] += 1
            continue

        for alias in aliases_by_table:
            if alias.amount_column not in loaded.dataframe.columns:
                continue

            raw_amount = parse_decimal(row.get(alias.amount_column))
            if raw_amount is None:
                stats["skipped_missing_adjustment_values"] += 1
                continue
            if raw_amount == 0:
                stats["skipped_zero_adjustment_values"] += 1
                continue
            if alias.review_status == "needs_review" and not allow_review_adjustments:
                stats["skipped_review_adjustment_values"] += 1
                continue
            if alias.sign_rule == "review_required" and not allow_review_adjustments:
                stats["skipped_review_adjustment_values"] += 1
                continue

            adjustment_row = build_adjustment_row(
                source_system=source_system,
                source_table=loaded.table_name,
                store_name=store_name,
                loaded=loaded,
                row_number=row_number,
                row=row,
                alias=alias,
                raw_amount=raw_amount,
            )
            if adjustment_row:
                rows.append(adjustment_row)
            else:
                stats["skipped_without_adjustment_id"] += 1

    return rows, stats


def load_adjustment_source_dataframe_from_files(
    *,
    files: list[MarketplaceFile],
    source_folder: str | Path,
    source_system: str,
    aliases: list[FeeAlias],
    allow_review_adjustments: bool,
) -> tuple[pd.DataFrame, dict[str, int]]:
    all_rows: list[dict[str, Any]] = []
    totals = ExtractionStats(income_files=len(files)).as_dict()

    logger.info("Source mode : folder")
    logger.info("Source root : %s", Path(source_folder).expanduser().resolve())
    logger.info("Income files: %s", len(files))

    for index, item in enumerate(files, 1):
        logger.info("[%s/%s] Load %s", index, len(files), item.path)
        for loaded in read_income_file(item):
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
            totals["loaded_income_rows"] += len(df)
            rows, stats = extract_frame_adjustment_rows(
                source_system=source_system,
                loaded=loaded,
                store_name=item.store_name,
                aliases=aliases,
                allow_review_adjustments=allow_review_adjustments,
            )
            all_rows.extend(rows)
            for key, value in stats.items():
                totals[key] += value

    adjustment_df = pd.DataFrame(all_rows, columns=TEMP_ADJUSTMENT_COLUMNS)
    if not adjustment_df.empty:
        adjustment_df["adjustment_source_sequence"] = range(1, len(adjustment_df) + 1)
    logger.info("Loaded income rows: %s", totals["loaded_income_rows"])
    logger.info("Extracted non-zero adjustment rows: %s", len(adjustment_df))
    return adjustment_df, totals


def create_temp_adjustment_source_table(conn, df: pd.DataFrame) -> None:
    insert_df = df.copy()
    for column in ["raw_adjustment_amount", "signed_adjustment_amount"]:
        if column in insert_df.columns:
            insert_df[column] = insert_df[column].map(lambda value: None if pd.isna(value) else str(value))

    insert_df.to_sql(
        TEMP_ADJUSTMENT_TABLE,
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    logger.info(
        "Temporary adjustment source table created: pg_temp.%s rows=%s",
        TEMP_ADJUSTMENT_TABLE,
        len(insert_df),
    )

    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_ADJUSTMENT_TABLE} ("source_system")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_ADJUSTMENT_TABLE} ("adjustment_source_sequence")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_ADJUSTMENT_TABLE} ("normalized_store_name")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_ADJUSTMENT_TABLE} ("external_adjustment_id")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_ADJUSTMENT_TABLE} ("related_external_order_id")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_ADJUSTMENT_TABLE} ("raw_record_id")'))
    conn.execute(text(f"ANALYZE pg_temp.{TEMP_ADJUSTMENT_TABLE}"))
    logger.info("Temporary adjustment source table indexed/analyzed: pg_temp.%s", TEMP_ADJUSTMENT_TABLE)


def configure_transaction_guardrails(conn, *, source_system: str) -> None:
    lock_key = f"sales_adjustment_phase_4:{source_system}"
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
    audit_sql = ctx.render_sql("sales_settlement_adjustment_audit.sql")
    insert_sql = ctx.render_sql("sales_settlement_adjustment_insert.sql")
    engine = get_engine(args.database)
    inserted_rows = 0
    total_adjustment_rows = 0

    with engine.connect() as conn:
        with conn.begin():
            configure_transaction_guardrails(conn, source_system=args.source_system)
            aliases = fetch_fee_aliases(
                conn,
                source_system=args.source_system,
                target_schema=args.target_schema,
            )
        phase4_aliases = [alias for alias in aliases if is_phase4_alias(alias)]
        logger.info("Active Phase 4 adjustment aliases: %s", len(phase4_aliases))

        files = discover_income_files(
            args.source_folder,
            args.source_system,
            limit_files=args.limit_files,
        )
        file_batches = chunked(files, args.file_batch_size)
        logger.info("File batches: %s batch_size=%s", len(file_batches), args.file_batch_size or "all")

        for batch_index, batch_files in enumerate(file_batches, 1):
            logger.info(
                "Process file batch %s/%s files=%s",
                batch_index,
                len(file_batches),
                len(batch_files),
            )
            adjustment_df, extraction_stats = load_adjustment_source_dataframe_from_files(
                files=batch_files,
                source_folder=args.source_folder,
                source_system=args.source_system,
                aliases=phase4_aliases,
                allow_review_adjustments=args.allow_review_adjustments,
            )
            total_adjustment_rows += len(adjustment_df)

            try:
                with conn.begin():
                    configure_transaction_guardrails(conn, source_system=args.source_system)
                    create_temp_adjustment_source_table(conn, adjustment_df)

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
                        "Transform blocked: adjustment rows with unmapped stores detected. "
                        "Fix store mappings or rerun with --allow-unmapped-store for controlled testing."
                    )

                logger.info("Execute transform source_system=%s", args.source_system)
                logger.info("Insert settlement adjustment rows batch_size=%s", args.insert_batch_size)
                source_adjustment_rows = len(adjustment_df)
                for row_batch_start in range(1, source_adjustment_rows + 1, args.insert_batch_size):
                    row_batch_end = min(row_batch_start + args.insert_batch_size, source_adjustment_rows + 1)
                    with conn.begin():
                        configure_transaction_guardrails(conn, source_system=args.source_system)
                        result = conn.execute(
                            text(insert_sql),
                            {"batch_start": row_batch_start, "batch_end": row_batch_end},
                        )
                    inserted_rows += max(result.rowcount or 0, 0)
                    logger.info(
                        "Insert settlement adjustment batch done: file_batch=%s row_start=%s row_end=%s rows=%s total_inserted=%s",
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
                            conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{TEMP_ADJUSTMENT_TABLE}"))
                except Exception as exc:
                    logger.warning("Could not drop temp table after file batch: %s", exc)

        if args.execute:
            with conn.begin():
                configure_transaction_guardrails(conn, source_system=args.source_system)
                conn.execute(text(f"ANALYZE {args.target_schema}.fact_sales_settlement_adjustment"))

    logger.info(
        "Transform finished. source_adjustment_rows=%s adjustment_rows=%s",
        total_adjustment_rows,
        inserted_rows,
    )


if __name__ == "__main__":
    main()
