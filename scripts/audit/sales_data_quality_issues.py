"""Populate data-quality issues from sales money-flow reconciliation checks.

The script is dry-run by default. Use --execute after reviewing the summary.
It records link/coverage issues without changing any Phase 1-5 fact rows.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.transform.context import validate_identifier


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


ISSUE_TYPES = [
    "phase1_order_without_settlement",
    "phase2_settlement_without_order",
    "phase4_adjustment_without_settlement",
    "phase5_balance_order_id_without_order_match",
    "phase5_balance_order_id_without_settlement_match",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create/update data_quality_issue rows for sales phase reconciliation gaps."
    )
    parser.add_argument("--database", default=None)
    parser.add_argument("--target-schema", default="public")
    parser.add_argument(
        "--source-system",
        choices=["lazada", "shopee", "tiktok_tokopedia"],
        default=None,
        help="Optional; process one marketplace only. Defaults to all.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write issue rows. Without this flag the script only prints/exports summary.",
    )
    parser.add_argument(
        "--close-resolved",
        action="store_true",
        help="Mark old open issues from this script as resolved when they are no longer detected.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run identifier stored on inserted/updated issue rows.",
    )
    parser.add_argument(
        "--export-summary",
        default=None,
        help="Optional CSV path for issue summary.",
    )
    return parser.parse_args()


def source_filter_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"AND (:source_system IS NULL OR {prefix}source_system = :source_system)"


def current_issues_body_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
        SELECT
            CONCAT_WS(
                '|',
                'sales_money_flow',
                'phase2_settlement_without_order',
                fss.source_system,
                'fact_sales_settlement',
                fss.sales_settlement_id::text
            ) AS issue_key,
            'sales_money_flow'::text AS issue_domain,
            'phase2_settlement_without_order'::text AS issue_type,
            'warning'::text AS issue_severity,
            'open'::text AS issue_status,
            fss.source_system,
            fss.sales_channel_type,
            'fact_sales_settlement'::text AS source_table,
            'sales_settlement_id'::text AS source_pk_name,
            fss.sales_settlement_id::text AS source_pk_value,
            fss.marketplace_id,
            fss.store_id,
            fss.sales_order_id,
            fss.sales_settlement_id,
            NULL::bigint AS sales_settlement_adjustment_id,
            NULL::bigint AS balance_transaction_id,
            fss.external_order_id,
            fss.external_order_item_id,
            NULL::text AS external_transaction_id,
            NULL::text AS external_adjustment_id,
            fss.settlement_amount AS issue_amount,
            fss.currency_code,
            'Settlement/income row exists, but no matching Phase 1 order was found.'::text AS issue_description,
            'Keep settlement as valid marketplace money data; exclude from order/SKU-level analysis until source order is found.'::text AS recommended_treatment,
            fss.source_file,
            fss.source_sheet,
            fss.source_row_number,
            fss.raw_record_id,
            jsonb_build_object(
                'settlement_type', fss.settlement_type,
                'settlement_status', fss.settlement_status,
                'settled_at', fss.settled_at,
                'released_at', fss.released_at
            ) AS metadata
        FROM {target_schema}.fact_sales_settlement fss
        WHERE fss.sales_channel_type = 'online'
          AND fss.sales_order_id IS NULL
          {source_filter_sql("fss")}

        UNION ALL

        SELECT
            CONCAT_WS(
                '|',
                'sales_money_flow',
                'phase4_adjustment_without_settlement',
                fssa.source_system,
                'fact_sales_settlement_adjustment',
                fssa.sales_settlement_adjustment_id::text
            ) AS issue_key,
            'sales_money_flow'::text AS issue_domain,
            'phase4_adjustment_without_settlement'::text AS issue_type,
            'info'::text AS issue_severity,
            'open'::text AS issue_status,
            fssa.source_system,
            fssa.sales_channel_type,
            'fact_sales_settlement_adjustment'::text AS source_table,
            'sales_settlement_adjustment_id'::text AS source_pk_name,
            fssa.sales_settlement_adjustment_id::text AS source_pk_value,
            fssa.marketplace_id,
            fssa.store_id,
            fssa.sales_order_id,
            fssa.sales_settlement_id,
            fssa.sales_settlement_adjustment_id,
            NULL::bigint AS balance_transaction_id,
            fssa.related_external_order_id AS external_order_id,
            NULL::text AS external_order_item_id,
            NULL::text AS external_transaction_id,
            fssa.external_adjustment_id,
            fssa.signed_adjustment_amount AS issue_amount,
            fssa.currency_code,
            'Adjustment row exists, but it is not linked to a Phase 2 settlement.'::text AS issue_description,
            'Keep as standalone marketplace adjustment; review only if downstream reporting requires settlement-level attribution.'::text AS recommended_treatment,
            fssa.source_file,
            fssa.source_sheet,
            fssa.source_row_number,
            fssa.raw_record_id,
            jsonb_build_object(
                'raw_adjustment_name', fssa.raw_adjustment_name,
                'raw_transaction_type', fssa.raw_transaction_type,
                'adjustment_scope', fssa.adjustment_scope,
                'adjustment_occurred_at', fssa.adjustment_occurred_at
            ) AS metadata
        FROM {target_schema}.fact_sales_settlement_adjustment fssa
        WHERE fssa.sales_channel_type = 'online'
          AND fssa.sales_settlement_id IS NULL
          {source_filter_sql("fssa")}

        UNION ALL

        SELECT
            CONCAT_WS(
                '|',
                'sales_money_flow',
                'phase5_balance_order_id_without_order_match',
                fbt.source_system,
                'fact_balance_transaction',
                fbt.balance_transaction_id::text
            ) AS issue_key,
            'sales_money_flow'::text AS issue_domain,
            'phase5_balance_order_id_without_order_match'::text AS issue_type,
            'warning'::text AS issue_severity,
            'open'::text AS issue_status,
            fbt.source_system,
            fbt.sales_channel_type,
            'fact_balance_transaction'::text AS source_table,
            'balance_transaction_id'::text AS source_pk_name,
            fbt.balance_transaction_id::text AS source_pk_value,
            fbt.marketplace_id,
            fbt.store_id,
            fbt.sales_order_id,
            fbt.sales_settlement_id,
            NULL::bigint AS sales_settlement_adjustment_id,
            fbt.balance_transaction_id,
            fbt.external_order_id,
            NULL::text AS external_order_item_id,
            fbt.external_transaction_id,
            NULL::text AS external_adjustment_id,
            fbt.signed_amount AS issue_amount,
            fbt.currency_code,
            'Balance/report row carries an order id, but no matching Phase 1 order was found.'::text AS issue_description,
            'Keep as balance ledger movement; exclude from order-level balance analysis until source order is found.'::text AS recommended_treatment,
            fbt.source_file,
            fbt.source_sheet,
            fbt.source_row_number,
            fbt.raw_record_id,
            jsonb_build_object(
                'transaction_type', fbt.transaction_type,
                'transaction_sub_type', fbt.transaction_sub_type,
                'transaction_status', fbt.transaction_status,
                'movement_direction', fbt.movement_direction,
                'transaction_occurred_at', fbt.transaction_occurred_at
            ) AS metadata
        FROM {target_schema}.fact_balance_transaction fbt
        WHERE fbt.sales_channel_type = 'online'
          AND fbt.external_order_id IS NOT NULL
          AND fbt.sales_order_id IS NULL
          {source_filter_sql("fbt")}

        UNION ALL

        SELECT
            CONCAT_WS(
                '|',
                'sales_money_flow',
                'phase5_balance_order_id_without_settlement_match',
                fbt.source_system,
                'fact_balance_transaction',
                fbt.balance_transaction_id::text
            ) AS issue_key,
            'sales_money_flow'::text AS issue_domain,
            'phase5_balance_order_id_without_settlement_match'::text AS issue_type,
            'warning'::text AS issue_severity,
            'open'::text AS issue_status,
            fbt.source_system,
            fbt.sales_channel_type,
            'fact_balance_transaction'::text AS source_table,
            'balance_transaction_id'::text AS source_pk_name,
            fbt.balance_transaction_id::text AS source_pk_value,
            fbt.marketplace_id,
            fbt.store_id,
            fbt.sales_order_id,
            fbt.sales_settlement_id,
            NULL::bigint AS sales_settlement_adjustment_id,
            fbt.balance_transaction_id,
            fbt.external_order_id,
            NULL::text AS external_order_item_id,
            fbt.external_transaction_id,
            NULL::text AS external_adjustment_id,
            fbt.signed_amount AS issue_amount,
            fbt.currency_code,
            'Balance/report row carries an order id, but no matching Phase 2 settlement was found.'::text AS issue_description,
            'Keep as balance ledger movement; exclude from settlement-linked balance analysis until matching settlement is found.'::text AS recommended_treatment,
            fbt.source_file,
            fbt.source_sheet,
            fbt.source_row_number,
            fbt.raw_record_id,
            jsonb_build_object(
                'transaction_type', fbt.transaction_type,
                'transaction_sub_type', fbt.transaction_sub_type,
                'transaction_status', fbt.transaction_status,
                'movement_direction', fbt.movement_direction,
                'transaction_occurred_at', fbt.transaction_occurred_at
            ) AS metadata
        FROM {target_schema}.fact_balance_transaction fbt
        WHERE fbt.sales_channel_type = 'online'
          AND fbt.external_order_id IS NOT NULL
          AND fbt.sales_settlement_id IS NULL
          {source_filter_sql("fbt")}

        UNION ALL

        SELECT
            CONCAT_WS(
                '|',
                'sales_money_flow',
                'phase1_order_without_settlement',
                fso.source_system,
                'fact_sales_order',
                fso.sales_order_id::text
            ) AS issue_key,
            'sales_money_flow'::text AS issue_domain,
            'phase1_order_without_settlement'::text AS issue_type,
            'info'::text AS issue_severity,
            'open'::text AS issue_status,
            fso.source_system,
            fso.sales_channel_type,
            'fact_sales_order'::text AS source_table,
            'sales_order_id'::text AS source_pk_name,
            fso.sales_order_id::text AS source_pk_value,
            fso.marketplace_id,
            fso.store_id,
            fso.sales_order_id,
            NULL::bigint AS sales_settlement_id,
            NULL::bigint AS sales_settlement_adjustment_id,
            NULL::bigint AS balance_transaction_id,
            fso.external_order_id,
            NULL::text AS external_order_item_id,
            NULL::text AS external_transaction_id,
            NULL::text AS external_adjustment_id,
            fso.net_order_amount AS issue_amount,
            fso.currency_code,
            'Phase 1 order exists, but no Phase 2 settlement was found for the same source/store/order grain.'::text AS issue_description,
            'Keep order as valid sales order; treat settlement status as missing/pending until income data catches up or source gap is accepted.'::text AS recommended_treatment,
            fso.source_file,
            fso.source_sheet,
            fso.source_row_number,
            fso.raw_record_id,
            jsonb_build_object(
                'order_date', fso.order_date,
                'order_status', fso.order_status,
                'payment_status', fso.payment_status
            ) AS metadata
        FROM {target_schema}.fact_sales_order fso
        WHERE fso.sales_channel_type = 'online'
          {source_filter_sql("fso")}
          AND NOT EXISTS (
              SELECT 1
              FROM {target_schema}.fact_sales_settlement fss
              WHERE fss.sales_channel_type = 'online'
                AND fss.source_system = fso.source_system
                AND fss.store_id IS NOT DISTINCT FROM fso.store_id
                AND fss.external_order_id = fso.external_order_id
          )
    """


def current_issues_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
    WITH current_issues AS (
        {current_issues_body_sql(target_schema)}
    )
    SELECT * FROM current_issues
    """


def summary_sql(target_schema: str) -> str:
    return f"""
    WITH current_issues AS (
        {current_issues_body_sql(target_schema)}
    )
    SELECT
        source_system,
        issue_type,
        issue_severity,
        COUNT(*) AS issue_rows,
        COALESCE(SUM(issue_amount), 0) AS issue_amount_sum
    FROM current_issues
    GROUP BY source_system, issue_type, issue_severity
    ORDER BY source_system, issue_type;
    """


def upsert_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
    WITH current_issues AS (
        {current_issues_body_sql(target_schema)}
    )
    INSERT INTO {target_schema}.data_quality_issue (
        issue_key,
        issue_domain,
        issue_type,
        issue_severity,
        issue_status,
        source_system,
        sales_channel_type,
        source_table,
        source_pk_name,
        source_pk_value,
        marketplace_id,
        store_id,
        sales_order_id,
        sales_settlement_id,
        sales_settlement_adjustment_id,
        balance_transaction_id,
        external_order_id,
        external_order_item_id,
        external_transaction_id,
        external_adjustment_id,
        issue_amount,
        currency_code,
        issue_description,
        recommended_treatment,
        source_file,
        source_sheet,
        source_row_number,
        raw_record_id,
        metadata,
        detected_by,
        run_id,
        first_detected_at,
        last_detected_at,
        resolved_at,
        created_at,
        updated_at
    )
    SELECT
        issue_key,
        issue_domain,
        issue_type,
        issue_severity,
        issue_status,
        source_system,
        sales_channel_type,
        source_table,
        source_pk_name,
        source_pk_value,
        marketplace_id,
        store_id,
        sales_order_id,
        sales_settlement_id,
        sales_settlement_adjustment_id,
        balance_transaction_id,
        external_order_id,
        external_order_item_id,
        external_transaction_id,
        external_adjustment_id,
        issue_amount,
        currency_code,
        issue_description,
        recommended_treatment,
        source_file,
        source_sheet,
        source_row_number,
        raw_record_id,
        metadata,
        'scripts/audit/sales_data_quality_issues.py',
        :run_id,
        now(),
        now(),
        NULL::timestamptz,
        now(),
        now()
    FROM current_issues
    ON CONFLICT (issue_key) DO UPDATE SET
        issue_severity = EXCLUDED.issue_severity,
        issue_status = CASE
            WHEN {target_schema}.data_quality_issue.issue_status = 'resolved' THEN 'open'
            ELSE {target_schema}.data_quality_issue.issue_status
        END,
        marketplace_id = EXCLUDED.marketplace_id,
        store_id = EXCLUDED.store_id,
        sales_order_id = EXCLUDED.sales_order_id,
        sales_settlement_id = EXCLUDED.sales_settlement_id,
        sales_settlement_adjustment_id = EXCLUDED.sales_settlement_adjustment_id,
        balance_transaction_id = EXCLUDED.balance_transaction_id,
        external_order_id = EXCLUDED.external_order_id,
        external_order_item_id = EXCLUDED.external_order_item_id,
        external_transaction_id = EXCLUDED.external_transaction_id,
        external_adjustment_id = EXCLUDED.external_adjustment_id,
        issue_amount = EXCLUDED.issue_amount,
        currency_code = EXCLUDED.currency_code,
        issue_description = EXCLUDED.issue_description,
        recommended_treatment = EXCLUDED.recommended_treatment,
        source_file = EXCLUDED.source_file,
        source_sheet = EXCLUDED.source_sheet,
        source_row_number = EXCLUDED.source_row_number,
        raw_record_id = EXCLUDED.raw_record_id,
        metadata = EXCLUDED.metadata,
        detected_by = EXCLUDED.detected_by,
        run_id = EXCLUDED.run_id,
        last_detected_at = now(),
        resolved_at = NULL,
        updated_at = now()
    RETURNING issue_key;
    """


def close_resolved_sql(target_schema: str) -> str:
    validate_identifier(target_schema, "target_schema")
    return f"""
    WITH current_issues AS (
        {current_issues_body_sql(target_schema)}
    )
    UPDATE {target_schema}.data_quality_issue dqi
    SET
        issue_status = 'resolved',
        resolved_at = now(),
        run_id = :run_id,
        updated_at = now()
    WHERE dqi.issue_domain = 'sales_money_flow'
      AND dqi.detected_by = 'scripts/audit/sales_data_quality_issues.py'
      AND dqi.issue_status = 'open'
      AND dqi.issue_type IN :issue_types
      AND (:source_system IS NULL OR dqi.source_system = :source_system)
      AND NOT EXISTS (
          SELECT 1
          FROM current_issues ci
          WHERE ci.issue_key = dqi.issue_key
      )
    RETURNING dqi.issue_key;
    """


def fetch_rows(conn, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    from sqlalchemy import bindparam, text

    stmt = text(sql).bindparams(bindparam("source_system"))
    result = conn.execute(stmt, params)
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


def print_summary(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("source_system,issue_type,issue_severity,issue_rows,issue_amount_sum")
        return

    columns = ["source_system", "issue_type", "issue_severity", "issue_rows", "issue_amount_sum"]
    print(",".join(columns))
    for row in rows:
        print(",".join(str(row.get(column, "")) for column in columns))


def main() -> None:
    args = parse_args()

    from sqlalchemy import bindparam, text

    from scripts.database.connection import get_engine

    target_schema = args.target_schema
    validate_identifier(target_schema, "target_schema")
    params = {"source_system": args.source_system, "run_id": args.run_id}

    engine = get_engine(args.database)
    logger.info(
        "Build sales data-quality issue set database=%s schema=%s source_system=%s",
        args.database,
        target_schema,
        args.source_system or "all",
    )

    with engine.begin() as conn:
        summary = fetch_rows(conn, summary_sql(target_schema), params)
        print_summary(summary)

        if args.export_summary:
            export_path = Path(args.export_summary).expanduser().resolve()
            write_csv(summary, export_path)
            logger.info("Summary export: %s", export_path)

        if not args.execute:
            logger.info("Dry-run only. Add --execute to upsert data_quality_issue rows.")
            return

        upserted_rows = conn.execute(
            text(upsert_sql(target_schema)).bindparams(bindparam("source_system")),
            params,
        ).fetchall()
        logger.info("Upserted data_quality_issue rows: %s", len(upserted_rows))

        if args.close_resolved:
            closed_rows = conn.execute(
                text(close_resolved_sql(target_schema)).bindparams(
                    bindparam("source_system"),
                    bindparam("issue_types", expanding=True),
                ),
                {
                    "source_system": args.source_system,
                    "run_id": args.run_id,
                    "issue_types": ISSUE_TYPES,
                },
            ).fetchall()
            logger.info("Closed resolved data_quality_issue rows: %s", len(closed_rows))


if __name__ == "__main__":
    main()
