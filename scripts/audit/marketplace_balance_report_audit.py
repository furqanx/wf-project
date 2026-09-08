"""Audit marketplace report files for Phase 5 balance movement planning.

This script is read-only. It scans folder-based staging report files and
summarizes balance/mutation rows before we design `fact_balance_transaction`.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.file_discovery import MarketplaceFile, discover_files
from scripts.loaders import lazada as lazada_loader
from scripts.loaders import shopee as shopee_loader
from scripts.loaders import tiktok_tokopedia as tiktok_tokopedia_loader
from scripts.loaders.common import LoadedFrame


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

MARKETPLACES = ("lazada", "shopee", "tiktok_tokopedia")


@dataclass
class BalanceAuditRow:
    source_system: str
    source_table: str
    store_name: str
    transaction_type: str
    transaction_sub_type: str
    transaction_status: str
    description_key: str
    file_count: int = 0
    row_count: int = 0
    non_null_amount_rows: int = 0
    non_zero_amount_rows: int = 0
    positive_amount_rows: int = 0
    negative_amount_rows: int = 0
    zero_amount_rows: int = 0
    amount_sum: Decimal = Decimal("0")
    amount_abs_sum: Decimal = Decimal("0")
    rows_with_external_transaction_id: int = 0
    rows_with_external_order_id: int = 0
    rows_with_balance_after: int = 0
    min_start_date: str = ""
    max_end_date: str = ""
    sample_descriptions: set[str] = field(default_factory=set)
    sample_files: set[str] = field(default_factory=set)

    def add_file(self, item: MarketplaceFile) -> None:
        self.file_count += 1
        if item.start_date and (not self.min_start_date or item.start_date < self.min_start_date):
            self.min_start_date = item.start_date
        if item.end_date and (not self.max_end_date or item.end_date > self.max_end_date):
            self.max_end_date = item.end_date
        if len(self.sample_files) < 3:
            self.sample_files.add(str(item.path))

    def to_dict(self) -> dict[str, object]:
        return {
            "source_system": self.source_system,
            "source_table": self.source_table,
            "store_name": self.store_name,
            "transaction_type": self.transaction_type,
            "transaction_sub_type": self.transaction_sub_type,
            "transaction_status": self.transaction_status,
            "description_key": self.description_key,
            "file_count": self.file_count,
            "row_count": self.row_count,
            "non_null_amount_rows": self.non_null_amount_rows,
            "non_zero_amount_rows": self.non_zero_amount_rows,
            "positive_amount_rows": self.positive_amount_rows,
            "negative_amount_rows": self.negative_amount_rows,
            "zero_amount_rows": self.zero_amount_rows,
            "amount_sum": str(self.amount_sum),
            "amount_abs_sum": str(self.amount_abs_sum),
            "rows_with_external_transaction_id": self.rows_with_external_transaction_id,
            "rows_with_external_order_id": self.rows_with_external_order_id,
            "rows_with_balance_after": self.rows_with_balance_after,
            "min_start_date": self.min_start_date,
            "max_end_date": self.max_end_date,
            "sample_descriptions": " | ".join(sorted(self.sample_descriptions)),
            "sample_files": " | ".join(sorted(self.sample_files)),
        }


@dataclass
class ReportSchemaRow:
    source_system: str
    source_table: str
    source_file: str
    source_sheet: str
    store_name: str
    row_count: int
    missing_columns: str
    ignored_columns: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_system": self.source_system,
            "source_table": self.source_table,
            "source_file": self.source_file,
            "source_sheet": self.source_sheet,
            "store_name": self.store_name,
            "row_count": self.row_count,
            "missing_columns": self.missing_columns,
            "ignored_columns": self.ignored_columns,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit marketplace report files for Phase 5 balance movement."
    )
    parser.add_argument(
        "--source-folder",
        default=str(PROJECT_ROOT / "data" / "staging"),
        help=(
            "Root folder containing sales_online/. For local snapshots use "
            "staging_snapshot_2026-08-11/data/staging."
        ),
    )
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "audit_reports"))
    parser.add_argument(
        "--marketplace",
        action="append",
        choices=MARKETPLACES,
        help="Marketplace to scan. Can be passed multiple times. Default: all.",
    )
    parser.add_argument("--limit-files", type=int, default=None)
    return parser.parse_args()


def clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text_value = str(value).strip()
    if not text_value or text_value.lower() in {"nan", "none", "null", "-"}:
        return None
    return text_value


def parse_decimal(value: Any) -> Decimal | None:
    text_value = clean_text(value)
    if text_value is None:
        return None

    is_parenthesized_negative = text_value.startswith("(") and text_value.endswith(")")
    cleaned = re.sub(r"[^0-9,.\-]", "", text_value)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", "")
    if cleaned in {"", "-", ".", "-."}:
        return None

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -abs(amount) if is_parenthesized_negative else amount


def normalize_value(value: Any) -> str:
    text_value = clean_text(value)
    if text_value is None:
        return "unspecified"
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text_value).strip("_").lower()
    return normalized or "unspecified"


def short_description_key(value: Any) -> str:
    text_value = clean_text(value)
    if text_value is None:
        return "unspecified"
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text_value).strip("_").lower()
    return normalized[:120] if normalized else "unspecified"


def discover_report_files(
    source_folder: str | Path,
    marketplace: str,
    *,
    limit_files: int | None,
) -> list[MarketplaceFile]:
    source_root = Path(source_folder).expanduser().resolve()
    search_roots = []
    if (source_root / "sales_online").exists():
        search_roots.append(source_root / "sales_online")
    search_roots.append(source_root)

    for root in search_roots:
        files = discover_files(root, marketplace=marketplace, phase="report")
        if files:
            return files[:limit_files] if limit_files else files
    return []


def read_report_file(item: MarketplaceFile) -> LoadedFrame:
    if item.marketplace == "lazada":
        return lazada_loader.read_report(item.path)
    if item.marketplace == "shopee":
        return shopee_loader.read_report(item.path)
    if item.marketplace == "tiktok_tokopedia":
        return tiktok_tokopedia_loader.read_report(item.path)
    raise ValueError(f"Unsupported marketplace: {item.marketplace}")


def transaction_fields(source_system: str, row: pd.Series) -> tuple[str, str, str, str]:
    if source_system == "lazada":
        return (
            normalize_value(row.get("type")),
            normalize_value(row.get("sub_type")),
            "unspecified",
            short_description_key(row.get("remarks")),
        )
    if source_system == "shopee":
        return (
            normalize_value(row.get("tipe_transaksi")),
            normalize_value(row.get("jenis_transaksi")),
            normalize_value(row.get("status")),
            short_description_key(row.get("deskripsi")),
        )
    if source_system == "tiktok_tokopedia":
        return (
            normalize_value(row.get("type")),
            "unspecified",
            normalize_value(row.get("status")),
            "unspecified",
        )
    return ("unspecified", "unspecified", "unspecified", "unspecified")


def amount_value(source_system: str, row: pd.Series) -> Decimal | None:
    if source_system == "shopee":
        return parse_decimal(row.get("jumlah"))
    return parse_decimal(row.get("amount"))


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


def balance_after(source_system: str, row: pd.Series) -> Decimal | None:
    if source_system == "shopee":
        return parse_decimal(row.get("saldo_akhir"))
    return None


def add_row_metrics(audit_row: BalanceAuditRow, *, source_system: str, row: pd.Series) -> None:
    amount = amount_value(source_system, row)
    if amount is not None:
        audit_row.non_null_amount_rows += 1
        if amount == 0:
            audit_row.zero_amount_rows += 1
        else:
            audit_row.non_zero_amount_rows += 1
            audit_row.amount_sum += amount
            audit_row.amount_abs_sum += abs(amount)
            if amount > 0:
                audit_row.positive_amount_rows += 1
            else:
                audit_row.negative_amount_rows += 1

    if external_transaction_id(source_system, row):
        audit_row.rows_with_external_transaction_id += 1
    if external_order_id(source_system, row):
        audit_row.rows_with_external_order_id += 1
    if balance_after(source_system, row) is not None:
        audit_row.rows_with_balance_after += 1

    if source_system in {"lazada", "shopee"}:
        description = clean_text(row.get("remarks")) or clean_text(row.get("deskripsi"))
        if description and len(audit_row.sample_descriptions) < 3:
            audit_row.sample_descriptions.add(description[:160])


def scan_files(
    *,
    source_folder: str | Path,
    marketplaces: Iterable[str],
    limit_files: int | None,
) -> tuple[list[BalanceAuditRow], list[ReportSchemaRow]]:
    rows_by_key: dict[tuple[str, str, str, str, str, str, str], BalanceAuditRow] = {}
    schema_rows: list[ReportSchemaRow] = []

    for marketplace in marketplaces:
        files = discover_report_files(source_folder, marketplace, limit_files=limit_files)
        logger.info("%s report files: %s", marketplace, len(files))
        for index, item in enumerate(files, 1):
            logger.info("[%s/%s] %s", index, len(files), item.path)
            loaded = read_report_file(item)
            df = loaded.dataframe
            store_name = item.store_name or "unknown"
            schema_rows.append(
                ReportSchemaRow(
                    source_system=marketplace,
                    source_table=loaded.table_name,
                    source_file=str(item.path),
                    source_sheet=loaded.sheet_name or "",
                    store_name=store_name,
                    row_count=len(df),
                    missing_columns=" | ".join(loaded.missing_columns),
                    ignored_columns=" | ".join(loaded.ignored_columns),
                )
            )

            for _, row in df.iterrows():
                transaction_type, transaction_sub_type, transaction_status, description_key = transaction_fields(
                    marketplace,
                    row,
                )
                key = (
                    marketplace,
                    loaded.table_name,
                    store_name,
                    transaction_type,
                    transaction_sub_type,
                    transaction_status,
                    description_key,
                )
                audit_row = rows_by_key.get(key)
                if audit_row is None:
                    audit_row = BalanceAuditRow(
                        source_system=marketplace,
                        source_table=loaded.table_name,
                        store_name=store_name,
                        transaction_type=transaction_type,
                        transaction_sub_type=transaction_sub_type,
                        transaction_status=transaction_status,
                        description_key=description_key,
                    )
                    rows_by_key[key] = audit_row
                audit_row.add_file(item)
                audit_row.row_count += 1
                add_row_metrics(audit_row, source_system=marketplace, row=row)

    return (
        sorted(
            rows_by_key.values(),
            key=lambda row: (
                row.source_system,
                row.store_name,
                row.transaction_type,
                row.transaction_sub_type,
                row.transaction_status,
                row.description_key,
            ),
        ),
        sorted(
            schema_rows,
            key=lambda row: (row.source_system, row.store_name, row.source_file),
        ),
    )


def write_csv(rows: list[Any], path: Path, fallback_fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].to_dict()) if rows else fallback_fieldnames
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def write_type_summary_csv(rows: list[BalanceAuditRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_system",
        "source_table",
        "transaction_type",
        "transaction_sub_type",
        "transaction_status",
        "store_count",
        "group_count",
        "row_count",
        "non_zero_amount_rows",
        "positive_amount_rows",
        "negative_amount_rows",
        "amount_sum",
        "amount_abs_sum",
        "rows_with_external_transaction_id",
        "rows_with_external_order_id",
        "rows_with_balance_after",
    ]
    summary: dict[tuple[str, str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "store_names": set(),
            "group_count": 0,
            "row_count": 0,
            "non_zero_amount_rows": 0,
            "positive_amount_rows": 0,
            "negative_amount_rows": 0,
            "amount_sum": Decimal("0"),
            "amount_abs_sum": Decimal("0"),
            "rows_with_external_transaction_id": 0,
            "rows_with_external_order_id": 0,
            "rows_with_balance_after": 0,
        }
    )
    for row in rows:
        key = (
            row.source_system,
            row.source_table,
            row.transaction_type,
            row.transaction_sub_type,
            row.transaction_status,
        )
        bucket = summary[key]
        bucket["store_names"].add(row.store_name)
        bucket["group_count"] += 1
        bucket["row_count"] += row.row_count
        bucket["non_zero_amount_rows"] += row.non_zero_amount_rows
        bucket["positive_amount_rows"] += row.positive_amount_rows
        bucket["negative_amount_rows"] += row.negative_amount_rows
        bucket["amount_sum"] += row.amount_sum
        bucket["amount_abs_sum"] += row.amount_abs_sum
        bucket["rows_with_external_transaction_id"] += row.rows_with_external_transaction_id
        bucket["rows_with_external_order_id"] += row.rows_with_external_order_id
        bucket["rows_with_balance_after"] += row.rows_with_balance_after

    output_rows = []
    for key, bucket in summary.items():
        source_system, source_table, transaction_type, transaction_sub_type, transaction_status = key
        output_rows.append(
            {
                "source_system": source_system,
                "source_table": source_table,
                "transaction_type": transaction_type,
                "transaction_sub_type": transaction_sub_type,
                "transaction_status": transaction_status,
                "store_count": len(bucket["store_names"]),
                "group_count": bucket["group_count"],
                "row_count": bucket["row_count"],
                "non_zero_amount_rows": bucket["non_zero_amount_rows"],
                "positive_amount_rows": bucket["positive_amount_rows"],
                "negative_amount_rows": bucket["negative_amount_rows"],
                "amount_sum": str(bucket["amount_sum"]),
                "amount_abs_sum": str(bucket["amount_abs_sum"]),
                "rows_with_external_transaction_id": bucket["rows_with_external_transaction_id"],
                "rows_with_external_order_id": bucket["rows_with_external_order_id"],
                "rows_with_balance_after": bucket["rows_with_balance_after"],
            }
        )

    output_rows.sort(
        key=lambda row: (
            row["source_system"],
            -Decimal(row["amount_abs_sum"]),
            row["transaction_type"],
            row["transaction_sub_type"],
            row["transaction_status"],
        )
    )

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


def write_markdown(rows: list[BalanceAuditRow], schema_rows: list[ReportSchemaRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary: dict[tuple[str, str], dict[str, Decimal | int]] = defaultdict(
        lambda: {
            "group_count": 0,
            "row_count": 0,
            "non_zero_amount_rows": 0,
            "amount_sum": Decimal("0"),
            "amount_abs_sum": Decimal("0"),
            "rows_with_external_transaction_id": 0,
            "rows_with_external_order_id": 0,
            "rows_with_balance_after": 0,
        }
    )
    for row in rows:
        bucket = summary[(row.source_system, row.source_table)]
        bucket["group_count"] += 1
        bucket["row_count"] += row.row_count
        bucket["non_zero_amount_rows"] += row.non_zero_amount_rows
        bucket["amount_sum"] += row.amount_sum
        bucket["amount_abs_sum"] += row.amount_abs_sum
        bucket["rows_with_external_transaction_id"] += row.rows_with_external_transaction_id
        bucket["rows_with_external_order_id"] += row.rows_with_external_order_id
        bucket["rows_with_balance_after"] += row.rows_with_balance_after

    schema_summary: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"file_count": 0, "loaded_rows": 0, "files_with_missing_columns": 0, "files_with_ignored_columns": 0}
    )
    for row in schema_rows:
        bucket = schema_summary[(row.source_system, row.source_table)]
        bucket["file_count"] += 1
        bucket["loaded_rows"] += row.row_count
        if row.missing_columns:
            bucket["files_with_missing_columns"] += 1
        if row.ignored_columns:
            bucket["files_with_ignored_columns"] += 1

    top_rows = sorted(rows, key=lambda row: row.amount_abs_sum, reverse=True)[:50]
    type_summary: dict[tuple[str, str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "store_names": set(),
            "group_count": 0,
            "row_count": 0,
            "non_zero_amount_rows": 0,
            "amount_sum": Decimal("0"),
            "amount_abs_sum": Decimal("0"),
        }
    )
    for row in rows:
        key = (
            row.source_system,
            row.source_table,
            row.transaction_type,
            row.transaction_sub_type,
            row.transaction_status,
        )
        bucket = type_summary[key]
        bucket["store_names"].add(row.store_name)
        bucket["group_count"] += 1
        bucket["row_count"] += row.row_count
        bucket["non_zero_amount_rows"] += row.non_zero_amount_rows
        bucket["amount_sum"] += row.amount_sum
        bucket["amount_abs_sum"] += row.amount_abs_sum
    top_types = sorted(
        type_summary.items(),
        key=lambda item: item[1]["amount_abs_sum"],
        reverse=True,
    )[:50]

    with path.open("w", encoding="utf-8") as f:
        f.write("# Marketplace Balance Report Audit\n\n")
        f.write(
            "Audit read-only untuk Phase 5. Sumbernya adalah folder `sales_online/*/report`, "
            "bukan tabel database staging. Tujuannya membaca pola mutasi saldo sebelum membuat "
            "`fact_balance_transaction`.\n\n"
        )

        f.write("## Source Summary\n\n")
        f.write(
            "| source_system | source_table | file_count | loaded_rows | files_with_missing_columns | files_with_ignored_columns |\n"
        )
        f.write("| --- | --- | ---: | ---: | ---: | ---: |\n")
        for (source_system, source_table), bucket in sorted(schema_summary.items()):
            f.write(
                f"| {source_system} | {source_table} | {bucket['file_count']} | "
                f"{bucket['loaded_rows']} | {bucket['files_with_missing_columns']} | "
                f"{bucket['files_with_ignored_columns']} |\n"
            )

        f.write("\n## Balance Movement Summary\n\n")
        f.write(
            "| source_system | source_table | group_count | row_count | non_zero_amount_rows | amount_sum | amount_abs_sum | external_tx_rows | external_order_rows | balance_after_rows |\n"
        )
        f.write("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        for (source_system, source_table), bucket in sorted(summary.items()):
            f.write(
                f"| {source_system} | {source_table} | {bucket['group_count']} | "
                f"{bucket['row_count']} | {bucket['non_zero_amount_rows']} | "
                f"{bucket['amount_sum']} | {bucket['amount_abs_sum']} | "
                f"{bucket['rows_with_external_transaction_id']} | "
                f"{bucket['rows_with_external_order_id']} | {bucket['rows_with_balance_after']} |\n"
            )

        f.write("\n## Top Transaction Types\n\n")
        f.write(
            "| source_system | transaction_type | transaction_sub_type | transaction_status | store_count | group_count | row_count | amount_sum | amount_abs_sum |\n"
        )
        f.write("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |\n")
        for (
            source_system,
            _source_table,
            transaction_type,
            transaction_sub_type,
            transaction_status,
        ), bucket in top_types:
            f.write(
                f"| {source_system} | {transaction_type} | {transaction_sub_type} | "
                f"{transaction_status} | {len(bucket['store_names'])} | {bucket['group_count']} | "
                f"{bucket['row_count']} | {bucket['amount_sum']} | {bucket['amount_abs_sum']} |\n"
            )

        f.write("\n## Top Amount Groups\n\n")
        f.write(
            "| source_system | store_name | transaction_type | transaction_sub_type | transaction_status | description_key | row_count | amount_sum | amount_abs_sum |\n"
        )
        f.write("| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |\n")
        for row in top_rows:
            f.write(
                f"| {row.source_system} | {row.store_name} | {row.transaction_type} | "
                f"{row.transaction_sub_type} | {row.transaction_status} | {row.description_key} | "
                f"{row.row_count} | {row.amount_sum} | {row.amount_abs_sum} |\n"
            )


def main() -> None:
    args = parse_args()
    marketplaces = args.marketplace or list(MARKETPLACES)
    output_dir = Path(args.output_dir).expanduser().resolve()

    rows, schema_rows = scan_files(
        source_folder=args.source_folder,
        marketplaces=marketplaces,
        limit_files=args.limit_files,
    )

    detail_csv = output_dir / "marketplace_balance_report_audit.csv"
    type_summary_csv = output_dir / "marketplace_balance_report_type_summary.csv"
    schema_csv = output_dir / "marketplace_balance_report_schema_audit.csv"
    markdown = output_dir / "marketplace_balance_report_audit.md"

    write_csv(
        rows,
        detail_csv,
        fallback_fieldnames=list(
            BalanceAuditRow(
                source_system="",
                source_table="",
                store_name="",
                transaction_type="",
                transaction_sub_type="",
                transaction_status="",
                description_key="",
            ).to_dict()
        ),
    )
    write_csv(
        schema_rows,
        schema_csv,
        fallback_fieldnames=list(
            ReportSchemaRow(
                source_system="",
                source_table="",
                source_file="",
                source_sheet="",
                store_name="",
                row_count=0,
                missing_columns="",
                ignored_columns="",
            ).to_dict()
        ),
    )
    write_type_summary_csv(rows, type_summary_csv)
    write_markdown(rows, schema_rows, markdown)

    logger.info("Detail output : %s", detail_csv)
    logger.info("Type output   : %s", type_summary_csv)
    logger.info("Schema output : %s", schema_csv)
    logger.info("MD output     : %s", markdown)


if __name__ == "__main__":
    main()
