"""Audit marketplace income files for Phase 4 adjustment candidates.

This script is read-only. It scans folder-based staging files and summarizes
fee-like income fields that look like settlement adjustments, refunds,
reversals, reimbursements, compensation, claims, penalties, or corrections.
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
FEE_AUDIT_CSV = PROJECT_ROOT / "audit_reports" / "marketplace_fee_name_audit.csv"

ADJUSTMENT_KEYWORD_RE = re.compile(
    "|".join(
        [
            r"adjustment",
            r"ajustment",
            r"penyesuaian",
            r"refund",
            r"pengembalian",
            r"return",
            r"retur",
            r"reversal",
            r"kompensasi",
            r"compensation",
            r"reimbursement",
            r"klaim",
            r"claim",
            r"chargeback",
            r"penalty",
            r"selisih",
            r"rebate",
        ]
    ),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FeeAuditDefinition:
    source_system: str
    source_table: str
    fee_source_kind: str
    raw_fee_name: str
    normalized_fee_name: str
    mapped_column: str
    amount_column: str


@dataclass
class AdjustmentAuditRow:
    source_system: str
    source_table: str
    fee_source_kind: str
    raw_fee_name: str
    normalized_fee_name: str
    mapped_column: str
    amount_column: str
    transaction_type: str
    candidate_reason: str
    recommended_treatment: str
    phase3_overlap_risk: str
    file_count: int = 0
    row_count: int = 0
    non_null_rows: int = 0
    non_zero_rows: int = 0
    positive_rows: int = 0
    negative_rows: int = 0
    zero_rows: int = 0
    amount_sum: Decimal = Decimal("0")
    amount_abs_sum: Decimal = Decimal("0")
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
            "source_table": self.source_table,
            "fee_source_kind": self.fee_source_kind,
            "raw_fee_name": self.raw_fee_name,
            "normalized_fee_name": self.normalized_fee_name,
            "mapped_column": self.mapped_column,
            "amount_column": self.amount_column,
            "transaction_type": self.transaction_type,
            "candidate_reason": self.candidate_reason,
            "recommended_treatment": self.recommended_treatment,
            "phase3_overlap_risk": self.phase3_overlap_risk,
            "file_count": self.file_count,
            "row_count": self.row_count,
            "non_null_rows": self.non_null_rows,
            "non_zero_rows": self.non_zero_rows,
            "positive_rows": self.positive_rows,
            "negative_rows": self.negative_rows,
            "zero_rows": self.zero_rows,
            "amount_sum": str(self.amount_sum),
            "amount_abs_sum": str(self.amount_abs_sum),
            "min_start_date": self.min_start_date,
            "max_end_date": self.max_end_date,
            "sample_files": " | ".join(sorted(self.sample_files)),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Phase 4 marketplace settlement adjustment candidates."
    )
    parser.add_argument(
        "--source-folder",
        default=str(PROJECT_ROOT / "data" / "staging"),
        help=(
            "Root folder containing sales_online/. For local snapshots use "
            "staging_snapshot_2026-08-11/data/staging."
        ),
    )
    parser.add_argument("--fee-audit-csv", default=str(FEE_AUDIT_CSV))
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


def normalize_transaction_type(value: Any) -> str:
    text_value = clean_text(value)
    if text_value is None:
        return "unspecified"
    return re.sub(r"[^a-zA-Z0-9]+", "_", text_value).strip("_").lower() or "unspecified"


def load_fee_definitions(path: str | Path, marketplaces: Iterable[str]) -> list[FeeAuditDefinition]:
    marketplace_set = set(marketplaces)
    definitions: list[FeeAuditDefinition] = []
    with Path(path).expanduser().open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["source_system"] not in marketplace_set:
                continue
            if row["phase"] != "income":
                continue
            if row["fee_source_kind"] not in {"column_fee", "row_fee_name"}:
                continue
            if not is_adjustment_candidate(row):
                continue
            definitions.append(
                FeeAuditDefinition(
                    source_system=row["source_system"],
                    source_table=row["source_table"],
                    fee_source_kind=row["fee_source_kind"],
                    raw_fee_name=row["raw_fee_name"],
                    normalized_fee_name=row["normalized_fee_name"],
                    mapped_column=row["mapped_column"],
                    amount_column=row["amount_column"],
                )
            )
    return definitions


def is_adjustment_candidate(row: dict[str, str]) -> bool:
    searchable = " ".join(
        [
            row.get("source_table", ""),
            row.get("raw_fee_name", ""),
            row.get("normalized_fee_name", ""),
            row.get("mapped_column", ""),
            row.get("amount_column", ""),
        ]
    )
    return bool(ADJUSTMENT_KEYWORD_RE.search(searchable))


def candidate_reason(definition: FeeAuditDefinition, transaction_type: str) -> str:
    reasons: list[str] = []
    if definition.source_table == "shopee_income_adjustment":
        reasons.append("shopee_adjustment_sheet")
    if ADJUSTMENT_KEYWORD_RE.search(definition.raw_fee_name):
        reasons.append("adjustment_keyword")
    if definition.source_system == "tiktok_tokopedia" and transaction_type not in {"order", "pesanan"}:
        reasons.append("tiktok_non_order_transaction")
    return "+".join(reasons) or "adjustment_candidate"


def recommended_treatment(definition: FeeAuditDefinition, transaction_type: str) -> str:
    if definition.source_system == "tiktok_tokopedia" and transaction_type not in {"order", "pesanan"}:
        return "phase4_candidate"
    if definition.source_table == "shopee_income_adjustment":
        return "phase4_candidate_review_phase3_overlap"
    return "review_phase3_or_phase4_boundary"


def phase3_overlap_risk(definition: FeeAuditDefinition, transaction_type: str) -> str:
    if definition.source_system == "tiktok_tokopedia" and transaction_type not in {"order", "pesanan"}:
        return "low_phase3_skipped_non_order"
    return "high_likely_already_in_phase3"


def discover_income_files(
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
        files = discover_files(root, marketplace=marketplace, phase="income")
        if files:
            return files[:limit_files] if limit_files else files
    return []


def read_income_file(item: MarketplaceFile) -> list[LoadedFrame]:
    if item.marketplace == "lazada":
        return [lazada_loader.read_income(item.path)]
    if item.marketplace == "shopee":
        return shopee_loader.read_income(item.path)
    if item.marketplace == "tiktok_tokopedia":
        return [tiktok_tokopedia_loader.read_income(item.path)]
    raise ValueError(f"Unsupported marketplace: {item.marketplace}")


def add_amount_metrics(row: AdjustmentAuditRow, amount: Decimal | None) -> None:
    row.non_null_rows += 1
    if amount is None:
        return
    if amount == 0:
        row.zero_rows += 1
        return
    row.non_zero_rows += 1
    row.amount_sum += amount
    row.amount_abs_sum += abs(amount)
    if amount > 0:
        row.positive_rows += 1
    else:
        row.negative_rows += 1


def scan_files(
    *,
    source_folder: str | Path,
    marketplaces: Iterable[str],
    definitions: list[FeeAuditDefinition],
    limit_files: int | None,
) -> list[AdjustmentAuditRow]:
    definitions_by_source_table: dict[tuple[str, str], list[FeeAuditDefinition]] = defaultdict(list)
    for definition in definitions:
        definitions_by_source_table[(definition.source_system, definition.source_table)].append(definition)

    rows_by_key: dict[tuple[str, str, str, str, str, str], AdjustmentAuditRow] = {}

    for marketplace in marketplaces:
        files = discover_income_files(source_folder, marketplace, limit_files=limit_files)
        logger.info("%s income files: %s", marketplace, len(files))
        for index, item in enumerate(files, 1):
            logger.info("[%s/%s] %s", index, len(files), item.path)
            for loaded in read_income_file(item):
                definitions_for_table = definitions_by_source_table.get(
                    (marketplace, loaded.table_name),
                    [],
                )
                if not definitions_for_table:
                    continue

                df = loaded.dataframe
                for definition in definitions_for_table:
                    if definition.fee_source_kind == "column_fee":
                        scan_column_fee(rows_by_key, item, loaded, df, definition)
                    elif definition.fee_source_kind == "row_fee_name":
                        scan_row_fee_name(rows_by_key, item, loaded, df, definition)

    return sorted(
        rows_by_key.values(),
        key=lambda row: (
            row.source_system,
            row.recommended_treatment,
            row.source_table,
            row.transaction_type,
            row.raw_fee_name.lower(),
        ),
    )


def upsert_audit_row(
    rows_by_key: dict[tuple[str, str, str, str, str, str], AdjustmentAuditRow],
    *,
    item: MarketplaceFile,
    definition: FeeAuditDefinition,
    transaction_type: str,
) -> AdjustmentAuditRow:
    reason = candidate_reason(definition, transaction_type)
    treatment = recommended_treatment(definition, transaction_type)
    overlap_risk = phase3_overlap_risk(definition, transaction_type)
    key = (
        definition.source_system,
        definition.source_table,
        definition.fee_source_kind,
        definition.raw_fee_name,
        transaction_type,
        treatment,
    )
    audit_row = rows_by_key.get(key)
    if audit_row is None:
        audit_row = AdjustmentAuditRow(
            source_system=definition.source_system,
            source_table=definition.source_table,
            fee_source_kind=definition.fee_source_kind,
            raw_fee_name=definition.raw_fee_name,
            normalized_fee_name=definition.normalized_fee_name,
            mapped_column=definition.mapped_column,
            amount_column=definition.amount_column,
            transaction_type=transaction_type,
            candidate_reason=reason,
            recommended_treatment=treatment,
            phase3_overlap_risk=overlap_risk,
        )
        rows_by_key[key] = audit_row
    audit_row.add_file(item)
    return audit_row


def scan_column_fee(
    rows_by_key: dict[tuple[str, str, str, str, str, str], AdjustmentAuditRow],
    item: MarketplaceFile,
    loaded: LoadedFrame,
    df: pd.DataFrame,
    definition: FeeAuditDefinition,
) -> None:
    if definition.amount_column not in df.columns:
        return

    grouped = df.groupby(
        df["type"].map(normalize_transaction_type) if "type" in df.columns else pd.Series(["unspecified"] * len(df)),
        dropna=False,
    )
    for transaction_type, group in grouped:
        audit_row = upsert_audit_row(
            rows_by_key,
            item=item,
            definition=definition,
            transaction_type=str(transaction_type),
        )
        audit_row.row_count += len(group)
        for value in group[definition.amount_column]:
            amount = parse_decimal(value)
            if clean_text(value) is not None:
                add_amount_metrics(audit_row, amount)


def scan_row_fee_name(
    rows_by_key: dict[tuple[str, str, str, str, str, str], AdjustmentAuditRow],
    item: MarketplaceFile,
    loaded: LoadedFrame,
    df: pd.DataFrame,
    definition: FeeAuditDefinition,
) -> None:
    if definition.mapped_column not in df.columns or definition.amount_column not in df.columns:
        return

    matched = df[df[definition.mapped_column].astype("string").str.strip() == definition.raw_fee_name]
    if matched.empty:
        return

    grouped = matched.groupby(
        matched["type"].map(normalize_transaction_type)
        if "type" in matched.columns
        else pd.Series(["unspecified"] * len(matched), index=matched.index),
        dropna=False,
    )
    for transaction_type, group in grouped:
        audit_row = upsert_audit_row(
            rows_by_key,
            item=item,
            definition=definition,
            transaction_type=str(transaction_type),
        )
        audit_row.row_count += len(group)
        for value in group[definition.amount_column]:
            amount = parse_decimal(value)
            if clean_text(value) is not None:
                add_amount_metrics(audit_row, amount)


def write_csv(rows: list[AdjustmentAuditRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].to_dict()) if rows else list(AdjustmentAuditRow(
        source_system="",
        source_table="",
        fee_source_kind="",
        raw_fee_name="",
        normalized_fee_name="",
        mapped_column="",
        amount_column="",
        transaction_type="",
        candidate_reason="",
        recommended_treatment="",
        phase3_overlap_risk="",
    ).to_dict())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def write_markdown(rows: list[AdjustmentAuditRow], path: Path) -> None:
    columns = [
        "source_system",
        "source_table",
        "raw_fee_name",
        "transaction_type",
        "recommended_treatment",
        "phase3_overlap_risk",
        "non_zero_rows",
        "amount_sum",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("# Marketplace Adjustment Candidate Audit\n\n")
        f.write(
            "Audit read-only untuk kandidat Phase 4 dari file income. "
            "`phase3_overlap_risk=high_likely_already_in_phase3` berarti kandidat perlu "
            "diputuskan: tetap di Phase 3 saja atau dipindah/dicerminkan ke Phase 4 "
            "tanpa double-counting.\n\n"
        )

        summary: dict[tuple[str, str], dict[str, Decimal | int]] = defaultdict(
            lambda: {
                "audit_rows": 0,
                "non_zero_rows": 0,
                "amount_sum": Decimal("0"),
                "amount_abs_sum": Decimal("0"),
            }
        )
        for row in rows:
            key = (row.source_system, row.recommended_treatment)
            summary[key]["audit_rows"] += 1
            summary[key]["non_zero_rows"] += row.non_zero_rows
            summary[key]["amount_sum"] += row.amount_sum
            summary[key]["amount_abs_sum"] += row.amount_abs_sum

        f.write("## Summary\n\n")
        f.write(
            "| source_system | recommended_treatment | audit_rows | non_zero_rows | amount_sum | amount_abs_sum |\n"
        )
        f.write("| --- | --- | --- | --- | --- | --- |\n")
        for key, data in sorted(summary.items()):
            f.write(
                f"| {key[0]} | {key[1]} | {data['audit_rows']} | "
                f"{data['non_zero_rows']} | {data['amount_sum']} | {data['amount_abs_sum']} |\n"
            )

        f.write("\n## Top Candidates By Absolute Amount\n\n")
        f.write("| " + " | ".join(columns) + " |\n")
        f.write("| " + " | ".join(["---"] * len(columns)) + " |\n")
        top_rows = sorted(rows, key=lambda row: row.amount_abs_sum, reverse=True)[:25]
        for row in top_rows:
            data = row.to_dict()
            values = [str(data[column]).replace("|", "\\|") for column in columns]
            f.write("| " + " | ".join(values) + " |\n")

        f.write("\n## Detail\n\n")
        f.write("| " + " | ".join(columns) + " |\n")
        f.write("| " + " | ".join(["---"] * len(columns)) + " |\n")
        for row in rows:
            data = row.to_dict()
            values = [str(data[column]).replace("|", "\\|") for column in columns]
            f.write("| " + " | ".join(values) + " |\n")


def main() -> None:
    args = parse_args()
    marketplaces = args.marketplace or list(MARKETPLACES)
    output_dir = Path(args.output_dir).expanduser().resolve()

    definitions = load_fee_definitions(args.fee_audit_csv, marketplaces)
    logger.info("Adjustment candidate definitions: %s", len(definitions))

    rows = scan_files(
        source_folder=args.source_folder,
        marketplaces=marketplaces,
        definitions=definitions,
        limit_files=args.limit_files,
    )

    csv_path = output_dir / "marketplace_adjustment_candidate_audit.csv"
    md_path = output_dir / "marketplace_adjustment_candidate_audit.md"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path)

    logger.info("Audit rows: %s", len(rows))
    logger.info("CSV output: %s", csv_path)
    logger.info("MD output : %s", md_path)


if __name__ == "__main__":
    main()
