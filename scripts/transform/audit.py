"""Small audit helpers for transform scripts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


@dataclass(frozen=True)
class AuditResult:
    rows: list[dict[str, Any]]

    def value(self, metric: str) -> int:
        for row in self.rows:
            if row.get("metric") == metric:
                return int(row.get("value") or 0)
        return 0

    def has_blocking_issues(self) -> bool:
        return self.value("unmapped_store_rows") > 0 or self.value("unmapped_product_rows") > 0


def rows_to_audit_result(rows: object) -> AuditResult:
    return AuditResult(rows=[dict(row._mapping) for row in rows])


def run_audit(engine: Engine, sql: str) -> AuditResult:
    with engine.connect() as conn:
        return run_audit_on_connection(conn, sql)


def run_audit_on_connection(conn: Connection, sql: str) -> AuditResult:
    result = conn.execute(text(sql))
    return rows_to_audit_result(result)


def print_audit(result: AuditResult) -> None:
    print("metric,value,notes")
    for row in result.rows:
        print(f"{row.get('metric')},{row.get('value')},{row.get('notes') or ''}")
