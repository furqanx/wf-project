"""Audit Phase 4 adjustment candidate coverage against existing fact tables.

This script is read-only for permanent tables. It loads
audit_reports/marketplace_adjustment_candidate_audit.csv into a temporary table,
then checks whether Shopee/Lazada candidates are already represented in:

- fact_sales_settlement_fee_detail (Phase 3)
- fact_sales_settlement_adjustment (Phase 4)
- fee_type / fee_type_alias master metadata

The output helps decide which candidates must stay in Phase 3 and which remain
eligible for Phase 4 without double counting.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.transform.context import validate_identifier


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_AUDIT_CSV = PROJECT_ROOT / "audit_reports" / "marketplace_adjustment_candidate_audit.csv"
DEFAULT_DETAIL_CSV = PROJECT_ROOT / "audit_reports" / "marketplace_adjustment_phase_coverage_detail.csv"
DEFAULT_SUMMARY_CSV = PROJECT_ROOT / "audit_reports" / "marketplace_adjustment_phase_coverage_summary.csv"
DEFAULT_MD = PROJECT_ROOT / "audit_reports" / "marketplace_adjustment_phase_coverage.md"
TEMP_CANDIDATE_TABLE = "adjustment_phase_coverage_candidate"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Shopee/Lazada Phase 4 candidates against Phase 3/4 facts."
    )
    parser.add_argument("--audit-csv", default=str(DEFAULT_AUDIT_CSV))
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument(
        "--marketplace",
        action="append",
        choices=["shopee", "lazada", "tiktok_tokopedia"],
        help="Marketplace to include. Can be repeated. Default: shopee and lazada.",
    )
    parser.add_argument("--output-detail", default=str(DEFAULT_DETAIL_CSV))
    parser.add_argument("--output-summary", default=str(DEFAULT_SUMMARY_CSV))
    parser.add_argument("--output-md", default=str(DEFAULT_MD))
    return parser.parse_args()


def parse_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def parse_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0")


def phase2_possible_bucket(raw_fee_name: str) -> str:
    normalized = raw_fee_name.lower()
    if any(token in normalized for token in ["refund", "pengembalian dana", "retur"]):
        return "refund_amount"
    if any(token in normalized for token in ["ongkir", "shipping", "kirim", "logistik"]):
        return "shipping_amount"
    if any(token in normalized for token in ["omset", "revenue", "pendapatan"]):
        return "gross_or_settlement_amount"
    return "not_obvious_from_phase2_header"


def load_candidates(path: str | Path, marketplaces: set[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with Path(path).expanduser().open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["source_system"] not in marketplaces:
                continue
            if row["non_zero_rows"] in {"", "0"}:
                continue
            rows.append(
                {
                    "source_system": row["source_system"],
                    "source_table": row["source_table"],
                    "fee_source_kind": row["fee_source_kind"],
                    "raw_fee_name": row["raw_fee_name"],
                    "normalized_fee_name": row["normalized_fee_name"],
                    "mapped_column": row["mapped_column"],
                    "amount_column": row["amount_column"],
                    "transaction_type": row["transaction_type"],
                    "recommended_treatment": row["recommended_treatment"],
                    "phase3_overlap_risk": row["phase3_overlap_risk"],
                    "expected_non_zero_rows": parse_int(row["non_zero_rows"]),
                    "audit_amount_sum": parse_decimal(row["amount_sum"]),
                    "audit_amount_abs_sum": parse_decimal(row["amount_abs_sum"]),
                    "phase2_possible_bucket": phase2_possible_bucket(row["raw_fee_name"]),
                }
            )
    return pd.DataFrame(rows)


def create_temp_candidate_table(conn, candidates: pd.DataFrame) -> None:
    insert_df = candidates.copy()
    for column in ["audit_amount_sum", "audit_amount_abs_sum"]:
        insert_df[column] = insert_df[column].map(str)

    insert_df.to_sql(
        TEMP_CANDIDATE_TABLE,
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_CANDIDATE_TABLE} ("source_system")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_CANDIDATE_TABLE} ("raw_fee_name")'))
    conn.execute(text(f"ANALYZE pg_temp.{TEMP_CANDIDATE_TABLE}"))


def coverage_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
    WITH candidate AS (
        SELECT *
        FROM pg_temp.{TEMP_CANDIDATE_TABLE}
    ),
    fee_master AS (
        SELECT
            fta.source_system,
            fta.source_table,
            fta.raw_fee_name,
            ft.fee_type_id,
            ft.fee_code,
            ft.fee_name,
            ft.fee_category,
            ft.amount_behavior,
            ft.sign_rule,
            ft.include_in_fee_fact,
            ft.review_status
        FROM {target_schema}.fee_type_alias fta
        JOIN {target_schema}.fee_type ft
            ON ft.fee_type_id = fta.fee_type_id
    ),
    phase3 AS (
        SELECT
            source_system,
            raw_fee_name,
            COUNT(*) AS phase3_rows,
            SUM(signed_fee_amount) AS phase3_amount_sum
        FROM {target_schema}.fact_sales_settlement_fee_detail
        GROUP BY source_system, raw_fee_name
    ),
    phase4 AS (
        SELECT
            source_system,
            raw_adjustment_name AS raw_fee_name,
            COUNT(*) AS phase4_rows,
            SUM(signed_adjustment_amount) AS phase4_amount_sum
        FROM {target_schema}.fact_sales_settlement_adjustment
        GROUP BY source_system, raw_adjustment_name
    ),
    settlement_summary AS (
        SELECT
            source_system,
            COUNT(*) AS phase2_settlement_rows,
            COUNT(*) FILTER (WHERE refund_amount IS NOT NULL AND refund_amount <> 0) AS phase2_refund_rows,
            SUM(refund_amount) AS phase2_refund_amount,
            COUNT(*) FILTER (WHERE shipping_amount IS NOT NULL AND shipping_amount <> 0) AS phase2_shipping_rows,
            SUM(shipping_amount) AS phase2_shipping_amount,
            COUNT(*) FILTER (WHERE settlement_amount IS NOT NULL AND settlement_amount <> 0) AS phase2_settlement_amount_rows,
            SUM(settlement_amount) AS phase2_settlement_amount
        FROM {target_schema}.fact_sales_settlement
        GROUP BY source_system
    )
    SELECT
        c.source_system,
        c.source_table,
        c.raw_fee_name,
        c.transaction_type,
        c.recommended_treatment,
        c.phase3_overlap_risk,
        c.expected_non_zero_rows,
        c.audit_amount_sum::numeric AS audit_amount_sum,
        COALESCE(fm.fee_code, '') AS fee_code,
        COALESCE(fm.fee_category, '') AS fee_category,
        COALESCE(fm.amount_behavior, '') AS amount_behavior,
        COALESCE(fm.sign_rule, '') AS sign_rule,
        COALESCE(fm.include_in_fee_fact, false) AS include_in_fee_fact,
        COALESCE(fm.review_status, '') AS review_status,
        COALESCE(p3.phase3_rows, 0) AS phase3_rows,
        COALESCE(p3.phase3_amount_sum, 0) AS phase3_amount_sum,
        COALESCE(p4.phase4_rows, 0) AS phase4_rows,
        COALESCE(p4.phase4_amount_sum, 0) AS phase4_amount_sum,
        c.phase2_possible_bucket,
        COALESCE(ss.phase2_settlement_rows, 0) AS phase2_settlement_rows,
        COALESCE(ss.phase2_refund_rows, 0) AS phase2_refund_rows,
        COALESCE(ss.phase2_refund_amount, 0) AS phase2_refund_amount,
        COALESCE(ss.phase2_shipping_rows, 0) AS phase2_shipping_rows,
        COALESCE(ss.phase2_shipping_amount, 0) AS phase2_shipping_amount,
        CASE
            WHEN COALESCE(p4.phase4_rows, 0) > 0
                THEN 'already_in_phase4'
            WHEN COALESCE(p3.phase3_rows, 0) > 0
                THEN 'already_in_phase3_do_not_insert_phase4'
            WHEN COALESCE(fm.include_in_fee_fact, false) = false
                THEN 'not_fee_fact_check_phase2_header'
            WHEN c.source_system = 'shopee' AND c.source_table = 'shopee_income_adjustment'
                THEN 'phase4_candidate_needs_business_approval'
            WHEN c.raw_fee_name ILIKE '%klaim%'
              OR c.raw_fee_name ILIKE '%claim%'
              OR c.raw_fee_name ILIKE '%kompensasi%'
              OR c.raw_fee_name ILIKE '%compensation%'
              OR c.raw_fee_name ILIKE '%penyesuaian saldo%'
                THEN 'phase4_candidate_needs_business_approval'
            ELSE 'keep_in_phase3_or_review'
        END AS coverage_decision
    FROM candidate c
    LEFT JOIN fee_master fm
        ON fm.source_system = c.source_system
       AND fm.source_table = c.source_table
       AND fm.raw_fee_name = c.raw_fee_name
    LEFT JOIN phase3 p3
        ON p3.source_system = c.source_system
       AND p3.raw_fee_name = c.raw_fee_name
    LEFT JOIN phase4 p4
        ON p4.source_system = c.source_system
       AND p4.raw_fee_name = c.raw_fee_name
    LEFT JOIN settlement_summary ss
        ON ss.source_system = c.source_system
    ORDER BY
        c.source_system,
        coverage_decision,
        ABS(c.audit_amount_sum::numeric) DESC,
        c.raw_fee_name;
    """


def summary_rows(detail_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[tuple[str, str], dict[str, Any]] = {}
    for row in detail_rows:
        key = (row["source_system"], row["coverage_decision"])
        item = summary.setdefault(
            key,
            {
                "source_system": row["source_system"],
                "coverage_decision": row["coverage_decision"],
                "candidate_count": 0,
                "expected_non_zero_rows": 0,
                "audit_amount_sum": Decimal("0"),
                "phase3_rows": 0,
                "phase3_amount_sum": Decimal("0"),
                "phase4_rows": 0,
                "phase4_amount_sum": Decimal("0"),
            },
        )
        item["candidate_count"] += 1
        item["expected_non_zero_rows"] += int(row["expected_non_zero_rows"] or 0)
        item["audit_amount_sum"] += Decimal(str(row["audit_amount_sum"] or 0))
        item["phase3_rows"] += int(row["phase3_rows"] or 0)
        item["phase3_amount_sum"] += Decimal(str(row["phase3_amount_sum"] or 0))
        item["phase4_rows"] += int(row["phase4_rows"] or 0)
        item["phase4_amount_sum"] += Decimal(str(row["phase4_amount_sum"] or 0))
    return list(summary.values())


def write_csv(rows: list[dict[str, Any]], path: str | Path) -> Path:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def write_markdown(summary: list[dict[str, Any]], detail: list[dict[str, Any]], path: str | Path) -> Path:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("# Marketplace Adjustment Phase Coverage\n\n")
        f.write(
            "Audit read-only untuk melihat kandidat adjustment Shopee/Lazada sudah "
            "terwakili di Phase 3/Phase 4 atau masih perlu keputusan Phase 4.\n\n"
        )

        f.write("## Summary\n\n")
        summary_columns = [
            "source_system",
            "coverage_decision",
            "candidate_count",
            "expected_non_zero_rows",
            "audit_amount_sum",
            "phase3_rows",
            "phase3_amount_sum",
            "phase4_rows",
            "phase4_amount_sum",
        ]
        f.write("| " + " | ".join(summary_columns) + " |\n")
        f.write("| " + " | ".join(["---"] * len(summary_columns)) + " |\n")
        for row in sorted(summary, key=lambda item: (item["source_system"], item["coverage_decision"])):
            f.write("| " + " | ".join(str(row[column]) for column in summary_columns) + " |\n")

        f.write("\n## Detail\n\n")
        detail_columns = [
            "source_system",
            "source_table",
            "raw_fee_name",
            "expected_non_zero_rows",
            "audit_amount_sum",
            "fee_category",
            "sign_rule",
            "include_in_fee_fact",
            "phase3_rows",
            "phase3_amount_sum",
            "phase4_rows",
            "coverage_decision",
        ]
        f.write("| " + " | ".join(detail_columns) + " |\n")
        f.write("| " + " | ".join(["---"] * len(detail_columns)) + " |\n")
        for row in detail:
            values = [str(row[column]).replace("|", "\\|") for column in detail_columns]
            f.write("| " + " | ".join(values) + " |\n")
    return output_path


def main() -> None:
    args = parse_args()
    marketplaces = set(args.marketplace or ["shopee", "lazada"])
    candidates = load_candidates(args.audit_csv, marketplaces)
    logger.info("Candidate rows loaded: %s", len(candidates))
    if candidates.empty:
        raise RuntimeError("No candidate rows loaded from audit CSV.")

    engine = get_engine(args.database)
    with engine.connect() as conn:
        create_temp_candidate_table(conn, candidates)
        result = conn.execute(text(coverage_sql(args.target_schema)))
        detail_rows = [dict(row._mapping) for row in result]

    summary = summary_rows(detail_rows)
    detail_path = write_csv(detail_rows, args.output_detail)
    summary_path = write_csv(summary, args.output_summary)
    md_path = write_markdown(summary, detail_rows, args.output_md)

    logger.info("Detail output : %s", detail_path)
    logger.info("Summary output: %s", summary_path)
    logger.info("MD output     : %s", md_path)


if __name__ == "__main__":
    main()
