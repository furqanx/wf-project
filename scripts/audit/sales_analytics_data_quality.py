"""Run Sales analytics data-quality checks and optionally fail the workflow."""

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

SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit canonical and semantic Sales datasets."
    )
    parser.add_argument("--database", default=None)
    parser.add_argument("--target-schema", default="public")
    parser.add_argument(
        "--fail-on",
        choices=["never", "warning", "critical"],
        default="critical",
        help="Lowest issue severity that returns a failed process exit code.",
    )
    parser.add_argument("--export-summary", default=None)
    return parser.parse_args()


def fetch_checks(conn, target_schema: str) -> list[dict[str, Any]]:
    from sqlalchemy import text

    validate_identifier(target_schema, "target_schema")
    result = conn.execute(
        text(
            f"""
            SELECT check_name, severity, issue_count, issue_amount, description
            FROM {target_schema}.vw_sales_data_quality_monitor
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'warning' THEN 2
                    ELSE 3
                END,
                check_name
            """
        )
    )
    return [dict(row._mapping) for row in result]


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]]) -> None:
    print("check_name,severity,issue_count,issue_amount,status")
    for row in rows:
        issue_count = int(row["issue_count"] or 0)
        print(
            f"{row['check_name']},{row['severity']},{issue_count},"
            f"{row['issue_amount'] or 0},{'FAIL' if issue_count else 'PASS'}"
        )


def failing_checks(rows: list[dict[str, Any]], fail_on: str) -> list[dict[str, Any]]:
    if fail_on == "never":
        return []
    threshold = SEVERITY_RANK[fail_on]
    return [
        row
        for row in rows
        if int(row["issue_count"] or 0) > 0
        and SEVERITY_RANK[row["severity"]] >= threshold
    ]


def main() -> None:
    args = parse_args()

    from scripts.database.connection import get_engine

    engine = get_engine(args.database)
    with engine.connect() as conn:
        rows = fetch_checks(conn, args.target_schema)

    print_summary(rows)
    if args.export_summary:
        path = Path(args.export_summary).expanduser().resolve()
        write_csv(rows, path)
        logger.info("Data-quality summary export: %s", path)

    failures = failing_checks(rows, args.fail_on)
    if failures:
        names = ", ".join(
            f"{row['check_name']}={row['issue_count']}" for row in failures
        )
        raise RuntimeError(f"Sales data-quality checks failed: {names}")

    warnings = [
        row
        for row in rows
        if int(row["issue_count"] or 0) > 0 and row["severity"] == "warning"
    ]
    logger.info(
        "Sales data-quality checks passed. checks=%s warnings=%s fail_on=%s",
        len(rows),
        len(warnings),
        args.fail_on,
    )


if __name__ == "__main__":
    main()

