"""Audit marketplace order/income files for fee-like source names.

This script is intentionally read-only. It scans normalized staging files and
exports candidate fee names before Phase 3 mappings are curated.
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
from pathlib import Path
from typing import Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.file_discovery import MarketplaceFile, discover_files
from scripts.loaders import lazada as lazada_loader
from scripts.loaders import shopee as shopee_loader
from scripts.loaders import tiktok_tokopedia as tiktok_tokopedia_loader
from scripts.schema_maps.lazada import LAZADA_INCOME_COLUMN_MAP, LAZADA_ORDER_COLUMN_MAP
from scripts.schema_maps.shopee import (
    SHOPEE_INCOME_ADJ_COLUMN_MAP,
    SHOPEE_INCOME_MAIN_COLUMN_MAP,
    SHOPEE_INCOME_OPF_COLUMN_MAP,
    SHOPEE_INCOME_SD_COLUMN_MAP,
    SHOPEE_INCOME_SF_COLUMN_MAP,
    SHOPEE_ORDER_COLUMN_MAP,
)
from scripts.schema_maps.tiktok_tokopedia import (
    TIKTOK_INCOME_COLUMN_MAP,
    TIKTOK_ORDER_COLUMN_MAP,
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

MARKETPLACES = ("lazada", "shopee", "tiktok_tokopedia")
PHASES = ("income", "order")

FEE_KEYWORD_RE = re.compile(
    "|".join(
        [
            r"fee",
            r"biaya",
            r"komisi",
            r"commission",
            r"voucher",
            r"discount",
            r"diskon",
            r"cashback",
            r"campaign",
            r"kampanye",
            r"promo",
            r"promosi",
            r"shipping",
            r"ongkir",
            r"ongkos",
            r"refund",
            r"pengembalian",
            r"payment",
            r"pembayaran",
            r"tax",
            r"vat",
            r"wht",
            r"pajak",
            r"ppn",
            r"pph",
            r"bea",
            r"premi",
            r"insurance",
            r"asuransi",
            r"adjustment",
            r"ajustment",
            r"penyesuaian",
            r"compensation",
            r"kompensasi",
            r"subsidy",
            r"subsidi",
            r"coupon",
            r"chargeback",
            r"reimbursement",
            r"penalty",
        ]
    ),
    re.IGNORECASE,
)

NON_FEE_EXACT_COLUMNS = {
    "currency",
    "mata_uang",
    "source_file",
    "store_name",
    "uploaded_at",
    "loaded_at",
    "harga_setelah_diskon",
    "sku_subtotal_after_discount",
    "subtotal_after_seller_discounts",
    "subtotal_before_discounts",
    "subtotal_pengembalian_dana_setelah_diskon_penjual",
    "total_pembayaran",
    "total_payment",
    "order_amount",
    "paid_price",
    "unit_price",
    "harga_awal",
    "harga_asli_produk",
    "total_revenue",
    "total_pendapatan",
    "total_settlement_amount",
    "jumlah_penyelesaian_pembayaran",
    "total_penghasilan",
    "omset_penjualan",
}

NON_FEE_COLUMN_PARTS = {
    "address",
    "alamat",
    "city",
    "kota",
    "country",
    "province",
    "provinsi",
    "region",
    "district",
    "village",
    "zipcode",
    "post_code",
    "provider",
    "tracking",
    "name",
    "nama",
    "code",
    "kode",
    "status",
    "time",
    "date",
    "tanggal",
    "method",
    "metode",
    "period",
    "periode",
    "comment",
    "komentar",
    "premium",
}

NON_FEE_ID_PARTS = {
    "id",
    "ids",
    "nomor",
    "number",
    "no",
}

SHIPPING_FEE_PARTS = {
    "fee",
    "cost",
    "costs",
    "amount",
    "discount",
    "subsidy",
    "insurance",
    "ongkir",
    "ongkos",
    "biaya",
}

NARROW_FEE_NAME_COLUMNS = {
    ("lazada", "income", "lazada_income"): {
        "fee_name_column": "nama_biaya",
        "amount_column": "jumlah_termasuk_pajak",
    },
    ("shopee", "income", "shopee_income_adjustment"): {
        "fee_name_column": "tipe_penyesuaian_deskripsi",
        "amount_column": "biaya_penyesuaian",
    },
}

COLUMN_MAPS_BY_TABLE = {
    ("lazada", "order", "lazada_orders"): LAZADA_ORDER_COLUMN_MAP,
    ("lazada", "income", "lazada_income"): LAZADA_INCOME_COLUMN_MAP,
    ("shopee", "order", "shopee_orders"): SHOPEE_ORDER_COLUMN_MAP,
    ("shopee", "income", "shopee_income_main"): SHOPEE_INCOME_MAIN_COLUMN_MAP,
    ("shopee", "income", "shopee_income_order_processing_fee"): SHOPEE_INCOME_OPF_COLUMN_MAP,
    ("shopee", "income", "shopee_income_service_fee"): SHOPEE_INCOME_SF_COLUMN_MAP,
    ("shopee", "income", "shopee_income_shipping_discrepancy"): SHOPEE_INCOME_SD_COLUMN_MAP,
    ("shopee", "income", "shopee_income_adjustment"): SHOPEE_INCOME_ADJ_COLUMN_MAP,
    ("tiktok_tokopedia", "order", "tiktok_tokopedia_orders"): TIKTOK_ORDER_COLUMN_MAP,
    ("tiktok_tokopedia", "income", "tiktok_tokopedia_income"): TIKTOK_INCOME_COLUMN_MAP,
}


@dataclass
class FeeAuditRow:
    source_system: str
    phase: str
    source_table: str
    fee_source_kind: str
    raw_fee_name: str
    normalized_fee_name: str
    mapped_column: str = ""
    amount_column: str = ""
    file_count: int = 0
    row_count: int = 0
    non_null_rows: int = 0
    non_zero_rows: int = 0
    amount_sum: float = 0.0
    min_start_date: str = ""
    max_end_date: str = ""
    sample_files: set[str] = field(default_factory=set)

    def add_file(self, item: MarketplaceFile) -> None:
        self.file_count += 1
        if item.start_date:
            if not self.min_start_date or item.start_date < self.min_start_date:
                self.min_start_date = item.start_date
        if item.end_date:
            if not self.max_end_date or item.end_date > self.max_end_date:
                self.max_end_date = item.end_date
        if len(self.sample_files) < 3:
            self.sample_files.add(str(item.path))

    def to_dict(self) -> dict[str, object]:
        return {
            "source_system": self.source_system,
            "phase": self.phase,
            "source_table": self.source_table,
            "fee_source_kind": self.fee_source_kind,
            "raw_fee_name": self.raw_fee_name,
            "normalized_fee_name": self.normalized_fee_name,
            "mapped_column": self.mapped_column,
            "amount_column": self.amount_column,
            "file_count": self.file_count,
            "row_count": self.row_count,
            "non_null_rows": self.non_null_rows,
            "non_zero_rows": self.non_zero_rows,
            "amount_sum": round(self.amount_sum, 2),
            "min_start_date": self.min_start_date,
            "max_end_date": self.max_end_date,
            "sample_files": " | ".join(sorted(self.sample_files)),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit fee-like names from marketplace income/order staging files."
    )
    parser.add_argument(
        "--source-folder",
        default=str(PROJECT_ROOT / "data" / "staging"),
        help=(
            "Root folder containing sales_online/. For local snapshot use "
            "staging_snapshot_2026-08-11/data/staging."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "audit_reports"),
        help="Directory for CSV/MD audit outputs.",
    )
    parser.add_argument(
        "--marketplace",
        action="append",
        choices=MARKETPLACES,
        help="Marketplace to scan. Can be passed multiple times. Default: all.",
    )
    parser.add_argument(
        "--phase",
        action="append",
        choices=PHASES,
        help="Phase to scan. Can be passed multiple times. Default: income and order.",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="Optional first-N file limit per marketplace/phase for quick checks.",
    )
    return parser.parse_args()


def raw_names_by_normalized(column_map: dict[str, str]) -> dict[str, list[str]]:
    names: dict[str, list[str]] = defaultdict(list)
    for raw_name, normalized_name in column_map.items():
        names[normalized_name].append(raw_name)
    return dict(names)


def first_raw_name(
    source_system: str,
    phase: str,
    source_table: str,
    mapped_column: str,
) -> str:
    column_map = COLUMN_MAPS_BY_TABLE.get((source_system, phase, source_table), {})
    reverse_map = raw_names_by_normalized(column_map)
    raw_names = reverse_map.get(mapped_column) or [mapped_column]
    return " / ".join(raw_names)


def is_fee_like_column(column: str) -> bool:
    normalized = str(column).strip()
    if not normalized or normalized in NON_FEE_EXACT_COLUMNS:
        return False
    searchable = normalized.replace("_", " ").lower()
    compact = normalized.lower()
    parts = set(searchable.split())

    if parts & NON_FEE_ID_PARTS:
        return False

    if "shipping" in parts and not (parts & SHIPPING_FEE_PARTS):
        return False
    if any(part in compact for part in NON_FEE_COLUMN_PARTS):
        protected = {"fee", "biaya", "discount", "diskon", "voucher", "refund", "pengembalian"}
        shipping_cost = "shipping" in parts and bool(parts & SHIPPING_FEE_PARTS)
        if not (parts & protected) and not shipping_cost:
            return False

    return bool(FEE_KEYWORD_RE.search(searchable))


def to_numeric(series: pd.Series) -> pd.Series:
    normalized = (
        series.astype("string")
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "NaN": pd.NA})
        .str.replace(",", "", regex=False)
        .str.replace(".", "", regex=False)
    )
    return pd.to_numeric(normalized, errors="coerce")


def read_marketplace_file(item: MarketplaceFile) -> list:
    if item.marketplace == "lazada":
        loaded = (
            lazada_loader.read_income(item.path)
            if item.phase == "income"
            else lazada_loader.read_order(item.path)
        )
        return [loaded]
    if item.marketplace == "shopee":
        loaded = (
            shopee_loader.read_income(item.path)
            if item.phase == "income"
            else shopee_loader.read_order(item.path)
        )
        return loaded if isinstance(loaded, list) else [loaded]
    if item.marketplace == "tiktok_tokopedia":
        loaded = (
            tiktok_tokopedia_loader.read_income(item.path)
            if item.phase == "income"
            else tiktok_tokopedia_loader.read_order(item.path)
        )
        return [loaded]
    raise ValueError(f"Unsupported marketplace: {item.marketplace}")


def candidate_columns(df: pd.DataFrame) -> list[str]:
    return [column for column in df.columns if is_fee_like_column(str(column))]


def add_column_fee_audit(
    rows_by_key: dict[tuple[str, str, str, str, str, str], FeeAuditRow],
    *,
    item: MarketplaceFile,
    source_table: str,
    df: pd.DataFrame,
) -> None:
    narrow_config = NARROW_FEE_NAME_COLUMNS.get((item.marketplace, item.phase, source_table))
    narrow_columns = set(narrow_config.values()) if narrow_config else set()

    for column in candidate_columns(df):
        if str(column) in narrow_columns:
            continue

        values = df[column]
        numeric_values = to_numeric(values)
        non_null_rows = int(values.notna().sum())
        numeric_non_null_rows = int(numeric_values.notna().sum())
        non_zero_rows = int((numeric_values.fillna(0) != 0).sum())
        if non_null_rows == 0 or numeric_non_null_rows == 0:
            continue

        raw_name = first_raw_name(item.marketplace, item.phase, source_table, str(column))
        key = (item.marketplace, item.phase, source_table, "column_fee", raw_name, str(column))
        row = rows_by_key.get(key)
        if row is None:
            row = FeeAuditRow(
                source_system=item.marketplace,
                phase=item.phase,
                source_table=source_table,
                fee_source_kind="column_fee",
                raw_fee_name=raw_name,
                normalized_fee_name=str(column),
                mapped_column=str(column),
                amount_column=str(column),
            )
            rows_by_key[key] = row

        row.add_file(item)
        row.row_count += len(df)
        row.non_null_rows += non_null_rows
        row.non_zero_rows += non_zero_rows
        row.amount_sum += float(numeric_values.fillna(0).sum())


def add_narrow_fee_audit(
    rows_by_key: dict[tuple[str, str, str, str, str, str], FeeAuditRow],
    *,
    item: MarketplaceFile,
    source_table: str,
    df: pd.DataFrame,
) -> None:
    config = NARROW_FEE_NAME_COLUMNS.get((item.marketplace, item.phase, source_table))
    if not config:
        return

    fee_name_column = config["fee_name_column"]
    amount_column = config["amount_column"]
    if fee_name_column not in df.columns:
        return

    names = df[fee_name_column].astype("string").str.strip()
    values = to_numeric(df[amount_column]) if amount_column in df.columns else pd.Series(dtype=float)
    grouped = pd.DataFrame({"raw_fee_name": names, "amount": values})
    grouped = grouped.dropna(subset=["raw_fee_name"])
    grouped = grouped[grouped["raw_fee_name"] != ""]
    if grouped.empty:
        return

    for raw_fee_name, group in grouped.groupby("raw_fee_name", dropna=True):
        key = (
            item.marketplace,
            item.phase,
            source_table,
            "row_fee_name",
            str(raw_fee_name),
            str(raw_fee_name),
        )
        row = rows_by_key.get(key)
        if row is None:
            row = FeeAuditRow(
                source_system=item.marketplace,
                phase=item.phase,
                source_table=source_table,
                fee_source_kind="row_fee_name",
                raw_fee_name=str(raw_fee_name),
                normalized_fee_name=str(raw_fee_name),
                mapped_column=fee_name_column,
                amount_column=amount_column,
            )
            rows_by_key[key] = row

        row.add_file(item)
        row.row_count += len(group)
        row.non_null_rows += len(group)
        row.non_zero_rows += int((group["amount"].fillna(0) != 0).sum())
        row.amount_sum += float(group["amount"].fillna(0).sum())


def add_ignored_fee_candidate_audit(
    rows_by_key: dict[tuple[str, str, str, str, str, str], FeeAuditRow],
    *,
    item: MarketplaceFile,
    source_table: str,
    ignored_columns: list[str],
    captured_raw_fee_columns: set[str],
) -> None:
    for column in ignored_columns:
        if column in captured_raw_fee_columns:
            continue
        if not is_fee_like_column(column):
            continue

        key = (
            item.marketplace,
            item.phase,
            source_table,
            "ignored_column_candidate",
            column,
            column,
        )
        row = rows_by_key.get(key)
        if row is None:
            row = FeeAuditRow(
                source_system=item.marketplace,
                phase=item.phase,
                source_table=source_table,
                fee_source_kind="ignored_column_candidate",
                raw_fee_name=column,
                normalized_fee_name=column,
                mapped_column="",
                amount_column="",
            )
            rows_by_key[key] = row

        row.add_file(item)


def captured_raw_fee_columns_for_loaded(
    *,
    item: MarketplaceFile,
    source_table: str,
    df: pd.DataFrame,
) -> set[str]:
    column_map = COLUMN_MAPS_BY_TABLE.get((item.marketplace, item.phase, source_table), {})
    reverse_map = raw_names_by_normalized(column_map)
    captured: set[str] = set()
    narrow_config = NARROW_FEE_NAME_COLUMNS.get((item.marketplace, item.phase, source_table))
    narrow_columns = set(narrow_config.values()) if narrow_config else set()

    for column in candidate_columns(df):
        if str(column) in narrow_columns:
            continue
        captured.update(reverse_map.get(str(column), [str(column)]))

    return captured


def discover_phase_files(
    source_folder: str | Path,
    *,
    marketplace: str,
    phase: str,
    limit_files: int | None,
) -> list[MarketplaceFile]:
    source_root = Path(source_folder).expanduser().resolve()
    search_roots = []
    if (source_root / "sales_online").exists():
        search_roots.append(source_root / "sales_online")
    search_roots.append(source_root)

    for root in search_roots:
        files = discover_files(root, marketplace=marketplace, phase=phase)
        if files:
            return files[:limit_files] if limit_files else files
    return []


def scan_files(
    source_folder: str | Path,
    *,
    marketplaces: Iterable[str],
    phases: Iterable[str],
    limit_files: int | None,
) -> list[FeeAuditRow]:
    rows_by_key: dict[tuple[str, str, str, str, str, str], FeeAuditRow] = {}

    for marketplace in marketplaces:
        for phase in phases:
            files = discover_phase_files(
                source_folder,
                marketplace=marketplace,
                phase=phase,
                limit_files=limit_files,
            )
            logger.info("%s %s files: %s", marketplace, phase, len(files))
            for index, item in enumerate(files, 1):
                logger.info("[%s/%s] %s", index, len(files), item.path)
                loaded_frames = read_marketplace_file(item)
                captured_raw_fee_columns: set[str] = set()
                for loaded in loaded_frames:
                    captured_raw_fee_columns.update(
                        captured_raw_fee_columns_for_loaded(
                            item=item,
                            source_table=loaded.table_name,
                            df=loaded.dataframe,
                        )
                    )

                for loaded in loaded_frames:
                    df = loaded.dataframe
                    add_column_fee_audit(
                        rows_by_key,
                        item=item,
                        source_table=loaded.table_name,
                        df=df,
                    )
                    add_narrow_fee_audit(
                        rows_by_key,
                        item=item,
                        source_table=loaded.table_name,
                        df=df,
                    )
                    add_ignored_fee_candidate_audit(
                        rows_by_key,
                        item=item,
                        source_table=loaded.table_name,
                        ignored_columns=loaded.ignored_columns,
                        captured_raw_fee_columns=captured_raw_fee_columns,
                    )

    return sorted(
        rows_by_key.values(),
        key=lambda row: (
            row.source_system,
            row.phase,
            row.source_table,
            row.fee_source_kind,
            row.raw_fee_name.lower(),
        ),
    )


def write_csv(rows: list[FeeAuditRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].to_dict().keys()) if rows else [
        "source_system",
        "phase",
        "source_table",
        "fee_source_kind",
        "raw_fee_name",
        "normalized_fee_name",
        "mapped_column",
        "amount_column",
        "file_count",
        "row_count",
        "non_null_rows",
        "non_zero_rows",
        "amount_sum",
        "min_start_date",
        "max_end_date",
        "sample_files",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def write_markdown(rows: list[FeeAuditRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "source_system",
        "phase",
        "source_table",
        "fee_source_kind",
        "raw_fee_name",
        "normalized_fee_name",
        "non_zero_rows",
        "amount_sum",
    ]
    with path.open("w", encoding="utf-8") as f:
        f.write("| " + " | ".join(columns) + " |\n")
        f.write("| " + " | ".join(["---"] * len(columns)) + " |\n")
        for row in rows:
            data = row.to_dict()
            values = [str(data[column]).replace("|", "\\|") for column in columns]
            f.write("| " + " | ".join(values) + " |\n")


def main() -> None:
    args = parse_args()
    marketplaces = args.marketplace or list(MARKETPLACES)
    phases = args.phase or list(PHASES)
    output_dir = Path(args.output_dir).expanduser().resolve()

    rows = scan_files(
        args.source_folder,
        marketplaces=marketplaces,
        phases=phases,
        limit_files=args.limit_files,
    )

    csv_path = output_dir / "marketplace_fee_name_audit.csv"
    md_path = output_dir / "marketplace_fee_name_audit.md"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path)

    logger.info("Audit rows: %s", len(rows))
    logger.info("CSV output: %s", csv_path)
    logger.info("MD output : %s", md_path)


if __name__ == "__main__":
    main()
