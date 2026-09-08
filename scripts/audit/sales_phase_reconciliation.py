"""Audit reconciliation across online sales money-flow phases.

This script is read-only. It summarizes Phase 1 through Phase 5 tables and
highlights link/coverage gaps before we build accounting-facing marts.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Any

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

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "audit_reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit reconciliation across sales Phase 1-5 fact tables."
    )
    parser.add_argument("--database", default=None)
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def source_summary_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
    WITH source_systems AS (
        SELECT source_system FROM {target_schema}.fact_sales_order
        UNION
        SELECT source_system FROM {target_schema}.fact_sales_settlement
        UNION
        SELECT source_system FROM {target_schema}.fact_sales_settlement_fee_detail
        UNION
        SELECT source_system FROM {target_schema}.fact_sales_settlement_adjustment
        UNION
        SELECT source_system FROM {target_schema}.fact_balance_transaction
    ),
    phase1_order AS (
        SELECT
            source_system,
            COUNT(*) AS order_rows,
            SUM(gross_order_amount) AS gross_order_amount,
            SUM(discount_amount) AS order_discount_amount,
            SUM(shipping_fee_amount) AS order_shipping_amount,
            SUM(net_order_amount) AS net_order_amount
        FROM {target_schema}.fact_sales_order
        WHERE sales_channel_type = 'online'
        GROUP BY source_system
    ),
    phase1_item AS (
        SELECT
            fso.source_system,
            COUNT(*) AS item_rows,
            SUM(fsoi.gross_item_amount) AS gross_item_amount,
            SUM(fsoi.discount_amount) AS item_discount_amount,
            SUM(fsoi.net_item_amount) AS net_item_amount
        FROM {target_schema}.fact_sales_order_item fsoi
        JOIN {target_schema}.fact_sales_order fso
            ON fso.sales_order_id = fsoi.sales_order_id
        WHERE fso.sales_channel_type = 'online'
        GROUP BY fso.source_system
    ),
    phase1_addon AS (
        SELECT
            fso.source_system,
            COUNT(*) AS addon_rows,
            SUM(fsoa.net_addon_amount) AS net_addon_amount
        FROM {target_schema}.fact_sales_order_addon fsoa
        JOIN {target_schema}.fact_sales_order fso
            ON fso.sales_order_id = fsoa.sales_order_id
        WHERE fso.sales_channel_type = 'online'
        GROUP BY fso.source_system
    ),
    phase2 AS (
        SELECT
            source_system,
            COUNT(*) AS settlement_rows,
            COUNT(sales_order_id) AS settlement_rows_matched_to_order,
            COUNT(*) - COUNT(sales_order_id) AS settlement_rows_unmatched_to_order,
            SUM(gross_revenue_amount) AS settlement_gross_revenue_amount,
            SUM(refund_amount) AS settlement_refund_amount,
            SUM(seller_discount_amount) AS settlement_seller_discount_amount,
            SUM(platform_discount_amount) AS settlement_platform_discount_amount,
            SUM(shipping_amount) AS settlement_shipping_amount,
            SUM(total_fee_amount) AS settlement_total_fee_amount,
            SUM(settlement_amount) AS settlement_amount
        FROM {target_schema}.fact_sales_settlement
        WHERE sales_channel_type = 'online'
        GROUP BY source_system
    ),
    phase3 AS (
        SELECT
            source_system,
            COUNT(*) AS fee_detail_rows,
            COUNT(sales_settlement_id) AS fee_detail_rows_matched_to_settlement,
            COUNT(*) - COUNT(sales_settlement_id) AS fee_detail_rows_unmatched_to_settlement,
            SUM(raw_fee_amount) AS raw_fee_amount,
            SUM(signed_fee_amount) AS signed_fee_amount
        FROM {target_schema}.fact_sales_settlement_fee_detail
        WHERE sales_channel_type = 'online'
        GROUP BY source_system
    ),
    phase4 AS (
        SELECT
            source_system,
            COUNT(*) AS adjustment_rows,
            COUNT(sales_settlement_id) AS adjustment_rows_matched_to_settlement,
            SUM(raw_adjustment_amount) AS raw_adjustment_amount,
            SUM(signed_adjustment_amount) AS signed_adjustment_amount
        FROM {target_schema}.fact_sales_settlement_adjustment
        WHERE sales_channel_type = 'online'
        GROUP BY source_system
    ),
    phase5 AS (
        SELECT
            source_system,
            COUNT(*) AS balance_rows,
            COUNT(sales_order_id) AS balance_rows_matched_to_order,
            COUNT(sales_settlement_id) AS balance_rows_matched_to_settlement,
            COUNT(*) FILTER (WHERE external_order_id IS NOT NULL) AS balance_rows_with_external_order_id,
            COUNT(*) FILTER (WHERE movement_direction = 'credit') AS balance_credit_rows,
            COUNT(*) FILTER (WHERE movement_direction = 'debit') AS balance_debit_rows,
            COUNT(*) FILTER (WHERE movement_direction = 'zero') AS balance_zero_rows,
            SUM(signed_amount) AS balance_signed_amount,
            SUM(signed_amount) FILTER (WHERE movement_direction = 'credit') AS balance_credit_amount,
            SUM(signed_amount) FILTER (WHERE movement_direction = 'debit') AS balance_debit_amount
        FROM {target_schema}.fact_balance_transaction
        WHERE sales_channel_type = 'online'
        GROUP BY source_system
    )
    SELECT
        ss.source_system,
        COALESCE(p1o.order_rows, 0) AS phase1_order_rows,
        COALESCE(p1i.item_rows, 0) AS phase1_item_rows,
        COALESCE(p1a.addon_rows, 0) AS phase1_addon_rows,
        COALESCE(p2.settlement_rows, 0) AS phase2_settlement_rows,
        COALESCE(p3.fee_detail_rows, 0) AS phase3_fee_detail_rows,
        COALESCE(p4.adjustment_rows, 0) AS phase4_adjustment_rows,
        COALESCE(p5.balance_rows, 0) AS phase5_balance_rows,
        COALESCE(p2.settlement_rows_matched_to_order, 0) AS phase2_matched_order_rows,
        COALESCE(p2.settlement_rows_unmatched_to_order, 0) AS phase2_unmatched_order_rows,
        COALESCE(p3.fee_detail_rows_matched_to_settlement, 0) AS phase3_matched_settlement_rows,
        COALESCE(p3.fee_detail_rows_unmatched_to_settlement, 0) AS phase3_unmatched_settlement_rows,
        COALESCE(p4.adjustment_rows_matched_to_settlement, 0) AS phase4_matched_settlement_rows,
        COALESCE(p5.balance_rows_with_external_order_id, 0) AS phase5_rows_with_external_order_id,
        COALESCE(p5.balance_rows_matched_to_order, 0) AS phase5_matched_order_rows,
        COALESCE(p5.balance_rows_matched_to_settlement, 0) AS phase5_matched_settlement_rows,
        COALESCE(p1o.gross_order_amount, 0) AS phase1_gross_order_amount,
        COALESCE(p1o.order_discount_amount, 0) AS phase1_order_discount_amount,
        COALESCE(p1o.order_shipping_amount, 0) AS phase1_order_shipping_amount,
        COALESCE(p1o.net_order_amount, 0) AS phase1_net_order_amount,
        COALESCE(p1i.gross_item_amount, 0) AS phase1_gross_item_amount,
        COALESCE(p1i.item_discount_amount, 0) AS phase1_item_discount_amount,
        COALESCE(p1i.net_item_amount, 0) AS phase1_net_item_amount,
        COALESCE(p1a.net_addon_amount, 0) AS phase1_net_addon_amount,
        COALESCE(p2.settlement_gross_revenue_amount, 0) AS phase2_gross_revenue_amount,
        COALESCE(p2.settlement_refund_amount, 0) AS phase2_refund_amount,
        COALESCE(p2.settlement_seller_discount_amount, 0) AS phase2_seller_discount_amount,
        COALESCE(p2.settlement_platform_discount_amount, 0) AS phase2_platform_discount_amount,
        COALESCE(p2.settlement_shipping_amount, 0) AS phase2_shipping_amount,
        COALESCE(p2.settlement_total_fee_amount, 0) AS phase2_total_fee_amount,
        COALESCE(p2.settlement_amount, 0) AS phase2_settlement_amount,
        COALESCE(p3.raw_fee_amount, 0) AS phase3_raw_fee_amount,
        COALESCE(p3.signed_fee_amount, 0) AS phase3_signed_fee_amount,
        COALESCE(p4.raw_adjustment_amount, 0) AS phase4_raw_adjustment_amount,
        COALESCE(p4.signed_adjustment_amount, 0) AS phase4_signed_adjustment_amount,
        COALESCE(p5.balance_signed_amount, 0) AS phase5_balance_signed_amount,
        COALESCE(p5.balance_credit_rows, 0) AS phase5_balance_credit_rows,
        COALESCE(p5.balance_debit_rows, 0) AS phase5_balance_debit_rows,
        COALESCE(p5.balance_zero_rows, 0) AS phase5_balance_zero_rows,
        COALESCE(p5.balance_credit_amount, 0) AS phase5_balance_credit_amount,
        COALESCE(p5.balance_debit_amount, 0) AS phase5_balance_debit_amount
    FROM source_systems ss
    LEFT JOIN phase1_order p1o ON p1o.source_system = ss.source_system
    LEFT JOIN phase1_item p1i ON p1i.source_system = ss.source_system
    LEFT JOIN phase1_addon p1a ON p1a.source_system = ss.source_system
    LEFT JOIN phase2 p2 ON p2.source_system = ss.source_system
    LEFT JOIN phase3 p3 ON p3.source_system = ss.source_system
    LEFT JOIN phase4 p4 ON p4.source_system = ss.source_system
    LEFT JOIN phase5 p5 ON p5.source_system = ss.source_system
    ORDER BY ss.source_system;
    """


def issue_summary_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
    WITH checks AS (
        SELECT
            source_system,
            'phase2_settlement_without_order' AS issue_type,
            COUNT(*) AS row_count,
            COALESCE(SUM(settlement_amount), 0) AS amount_sum
        FROM {target_schema}.fact_sales_settlement
        WHERE sales_channel_type = 'online'
          AND sales_order_id IS NULL
        GROUP BY source_system
        UNION ALL
        SELECT
            source_system,
            'phase3_fee_without_settlement' AS issue_type,
            COUNT(*) AS row_count,
            COALESCE(SUM(signed_fee_amount), 0) AS amount_sum
        FROM {target_schema}.fact_sales_settlement_fee_detail
        WHERE sales_channel_type = 'online'
          AND sales_settlement_id IS NULL
        GROUP BY source_system
        UNION ALL
        SELECT
            source_system,
            'phase4_adjustment_without_settlement' AS issue_type,
            COUNT(*) AS row_count,
            COALESCE(SUM(signed_adjustment_amount), 0) AS amount_sum
        FROM {target_schema}.fact_sales_settlement_adjustment
        WHERE sales_channel_type = 'online'
          AND sales_settlement_id IS NULL
        GROUP BY source_system
        UNION ALL
        SELECT
            source_system,
            'phase5_balance_order_id_without_order_match' AS issue_type,
            COUNT(*) AS row_count,
            COALESCE(SUM(signed_amount), 0) AS amount_sum
        FROM {target_schema}.fact_balance_transaction
        WHERE sales_channel_type = 'online'
          AND external_order_id IS NOT NULL
          AND sales_order_id IS NULL
        GROUP BY source_system
        UNION ALL
        SELECT
            source_system,
            'phase5_balance_order_id_without_settlement_match' AS issue_type,
            COUNT(*) AS row_count,
            COALESCE(SUM(signed_amount), 0) AS amount_sum
        FROM {target_schema}.fact_balance_transaction
        WHERE sales_channel_type = 'online'
          AND external_order_id IS NOT NULL
          AND sales_settlement_id IS NULL
        GROUP BY source_system
        UNION ALL
        SELECT
            source_system,
            'phase5_balance_without_store' AS issue_type,
            COUNT(*) AS row_count,
            COALESCE(SUM(signed_amount), 0) AS amount_sum
        FROM {target_schema}.fact_balance_transaction
        WHERE sales_channel_type = 'online'
          AND store_id IS NULL
        GROUP BY source_system
    )
    SELECT *
    FROM checks
    WHERE row_count > 0
    ORDER BY source_system, issue_type;
    """


def balance_type_summary_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
    SELECT
        source_system,
        transaction_type,
        COALESCE(transaction_sub_type, '') AS transaction_sub_type,
        COALESCE(transaction_status, '') AS transaction_status,
        movement_direction,
        COUNT(*) AS row_count,
        COUNT(sales_order_id) AS matched_order_rows,
        COUNT(sales_settlement_id) AS matched_settlement_rows,
        SUM(signed_amount) AS signed_amount_sum,
        SUM(ABS(signed_amount)) AS signed_amount_abs_sum
    FROM {target_schema}.fact_balance_transaction
    WHERE sales_channel_type = 'online'
    GROUP BY
        source_system,
        transaction_type,
        COALESCE(transaction_sub_type, ''),
        COALESCE(transaction_status, ''),
        movement_direction
    ORDER BY source_system, signed_amount_abs_sum DESC;
    """


def order_settlement_reconciliation_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
    WITH order_amount AS (
        SELECT
            source_system,
            store_id,
            external_order_id,
            COUNT(*) AS order_rows,
            SUM(net_order_amount) AS net_order_amount,
            SUM(gross_order_amount) AS gross_order_amount
        FROM {target_schema}.fact_sales_order
        WHERE sales_channel_type = 'online'
        GROUP BY source_system, store_id, external_order_id
    ),
    settlement_amount AS (
        SELECT
            source_system,
            store_id,
            external_order_id,
            COUNT(*) AS settlement_rows,
            SUM(settlement_amount) AS settlement_amount,
            SUM(gross_revenue_amount) AS gross_revenue_amount,
            SUM(total_fee_amount) AS total_fee_amount,
            SUM(refund_amount) AS refund_amount
        FROM {target_schema}.fact_sales_settlement
        WHERE sales_channel_type = 'online'
        GROUP BY source_system, store_id, external_order_id
    ),
    fee_amount AS (
        SELECT
            source_system,
            store_id,
            external_order_id,
            COUNT(*) AS fee_rows,
            SUM(signed_fee_amount) AS signed_fee_amount
        FROM {target_schema}.fact_sales_settlement_fee_detail
        WHERE sales_channel_type = 'online'
        GROUP BY source_system, store_id, external_order_id
    ),
    balance_amount AS (
        SELECT
            source_system,
            store_id,
            external_order_id,
            COUNT(*) AS balance_rows,
            SUM(signed_amount) AS balance_signed_amount
        FROM {target_schema}.fact_balance_transaction
        WHERE sales_channel_type = 'online'
          AND external_order_id IS NOT NULL
        GROUP BY source_system, store_id, external_order_id
    ),
    joined AS (
        SELECT
            COALESCE(o.source_system, s.source_system, f.source_system, b.source_system) AS source_system,
            COALESCE(o.store_id, s.store_id, f.store_id, b.store_id) AS store_id,
            COALESCE(o.external_order_id, s.external_order_id, f.external_order_id, b.external_order_id) AS external_order_id,
            o.order_rows,
            s.settlement_rows,
            f.fee_rows,
            b.balance_rows,
            COALESCE(o.net_order_amount, 0) AS net_order_amount,
            COALESCE(o.gross_order_amount, 0) AS gross_order_amount,
            COALESCE(s.settlement_amount, 0) AS settlement_amount,
            COALESCE(s.gross_revenue_amount, 0) AS settlement_gross_revenue_amount,
            COALESCE(s.total_fee_amount, 0) AS settlement_total_fee_amount,
            COALESCE(s.refund_amount, 0) AS settlement_refund_amount,
            COALESCE(f.signed_fee_amount, 0) AS signed_fee_amount,
            COALESCE(b.balance_signed_amount, 0) AS balance_signed_amount
        FROM order_amount o
        FULL JOIN settlement_amount s
            ON s.source_system = o.source_system
           AND s.store_id = o.store_id
           AND s.external_order_id = o.external_order_id
        FULL JOIN fee_amount f
            ON f.source_system = COALESCE(o.source_system, s.source_system)
           AND f.store_id = COALESCE(o.store_id, s.store_id)
           AND f.external_order_id = COALESCE(o.external_order_id, s.external_order_id)
        FULL JOIN balance_amount b
            ON b.source_system = COALESCE(o.source_system, s.source_system, f.source_system)
           AND b.store_id = COALESCE(o.store_id, s.store_id, f.store_id)
           AND b.external_order_id = COALESCE(o.external_order_id, s.external_order_id, f.external_order_id)
    )
    SELECT
        source_system,
        COUNT(*) AS order_grain_rows,
        COUNT(*) FILTER (WHERE order_rows IS NOT NULL) AS grains_with_phase1_order,
        COUNT(*) FILTER (WHERE settlement_rows IS NOT NULL) AS grains_with_phase2_settlement,
        COUNT(*) FILTER (WHERE fee_rows IS NOT NULL) AS grains_with_phase3_fee,
        COUNT(*) FILTER (WHERE balance_rows IS NOT NULL) AS grains_with_phase5_balance,
        COUNT(*) FILTER (WHERE order_rows IS NOT NULL AND settlement_rows IS NULL) AS phase1_without_phase2_grains,
        COUNT(*) FILTER (WHERE settlement_rows IS NOT NULL AND order_rows IS NULL) AS phase2_without_phase1_grains,
        COUNT(*) FILTER (WHERE balance_rows IS NOT NULL AND order_rows IS NULL) AS phase5_order_id_without_phase1_grains,
        SUM(net_order_amount) AS net_order_amount,
        SUM(gross_order_amount) AS gross_order_amount,
        SUM(settlement_amount) AS settlement_amount,
        SUM(settlement_gross_revenue_amount) AS settlement_gross_revenue_amount,
        SUM(settlement_total_fee_amount) AS settlement_total_fee_amount,
        SUM(settlement_refund_amount) AS settlement_refund_amount,
        SUM(signed_fee_amount) AS signed_fee_amount,
        SUM(balance_signed_amount) AS order_linked_balance_signed_amount
    FROM joined
    GROUP BY source_system
    ORDER BY source_system;
    """


def fetch_rows(conn, sql: str) -> list[dict[str, Any]]:
    result = conn.execute(text(sql))
    return [dict(row._mapping) for row in result]


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        if not fieldnames:
            return
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    lines = []
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def write_markdown(
    *,
    source_summary: list[dict[str, Any]],
    issue_summary: list[dict[str, Any]],
    order_reconciliation: list[dict[str, Any]],
    balance_type_summary: list[dict[str, Any]],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    top_balance = balance_type_summary[:30]
    with path.open("w", encoding="utf-8") as f:
        f.write("# Sales Phase Reconciliation Audit\n\n")
        f.write(
            "Audit read-only untuk melihat hubungan Phase 1 sampai Phase 5. "
            "Angka ini belum menjadi rumus laba final; ini adalah kontrol kualitas "
            "coverage, linkage, dan arah movement.\n\n"
        )
        f.write("## Phase Row Summary\n\n")
        f.write(
            markdown_table(
                source_summary,
                [
                    "source_system",
                    "phase1_order_rows",
                    "phase1_item_rows",
                    "phase1_addon_rows",
                    "phase2_settlement_rows",
                    "phase3_fee_detail_rows",
                    "phase4_adjustment_rows",
                    "phase5_balance_rows",
                    "phase2_unmatched_order_rows",
                ],
            )
        )
        f.write("\n\n## Amount Summary\n\n")
        f.write(
            markdown_table(
                source_summary,
                [
                    "source_system",
                    "phase1_net_order_amount",
                    "phase2_settlement_amount",
                    "phase3_signed_fee_amount",
                    "phase4_signed_adjustment_amount",
                    "phase5_balance_signed_amount",
                    "phase5_balance_credit_amount",
                    "phase5_balance_debit_amount",
                ],
            )
        )
        f.write("\n\n## Link Issues\n\n")
        if issue_summary:
            f.write(markdown_table(issue_summary, ["source_system", "issue_type", "row_count", "amount_sum"]))
        else:
            f.write("No link issues found.\n")
        f.write("\n\n## Order Grain Coverage\n\n")
        f.write(
            markdown_table(
                order_reconciliation,
                [
                    "source_system",
                    "order_grain_rows",
                    "grains_with_phase1_order",
                    "grains_with_phase2_settlement",
                    "grains_with_phase3_fee",
                    "grains_with_phase5_balance",
                    "phase1_without_phase2_grains",
                    "phase2_without_phase1_grains",
                ],
            )
        )
        f.write("\n\n## Top Balance Types\n\n")
        f.write(
            markdown_table(
                top_balance,
                [
                    "source_system",
                    "transaction_type",
                    "transaction_sub_type",
                    "transaction_status",
                    "movement_direction",
                    "row_count",
                    "signed_amount_sum",
                    "signed_amount_abs_sum",
                ],
            )
        )
        f.write("\n")


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    target_schema = args.target_schema
    engine = get_engine(args.database)

    with engine.connect() as conn:
        logger.info("Run sales phase reconciliation audit database=%s schema=%s", args.database, target_schema)
        source_summary = fetch_rows(conn, source_summary_sql(target_schema))
        issue_summary = fetch_rows(conn, issue_summary_sql(target_schema))
        order_reconciliation = fetch_rows(conn, order_settlement_reconciliation_sql(target_schema))
        balance_type_summary = fetch_rows(conn, balance_type_summary_sql(target_schema))

    source_summary_path = output_dir / "sales_phase_reconciliation_summary.csv"
    issue_summary_path = output_dir / "sales_phase_reconciliation_issues.csv"
    order_reconciliation_path = output_dir / "sales_phase_order_grain_reconciliation.csv"
    balance_type_summary_path = output_dir / "sales_phase_balance_type_summary.csv"
    markdown_path = output_dir / "sales_phase_reconciliation_audit.md"

    write_csv(source_summary, source_summary_path)
    write_csv(issue_summary, issue_summary_path)
    write_csv(order_reconciliation, order_reconciliation_path)
    write_csv(balance_type_summary, balance_type_summary_path)
    write_markdown(
        source_summary=source_summary,
        issue_summary=issue_summary,
        order_reconciliation=order_reconciliation,
        balance_type_summary=balance_type_summary,
        path=markdown_path,
    )

    logger.info("Summary output      : %s", source_summary_path)
    logger.info("Issues output       : %s", issue_summary_path)
    logger.info("Order grain output  : %s", order_reconciliation_path)
    logger.info("Balance type output : %s", balance_type_summary_path)
    logger.info("MD output           : %s", markdown_path)


if __name__ == "__main__":
    main()
