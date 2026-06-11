from pathlib import Path
from typing import Any

from src.schema_contracts.models import PanderaColumnRule, SchemaIssue
from src.schema_contracts.validator import DEFAULT_CONTRACT_PATH, get_contract


def _issue(severity: str, drift_type: str, column_name: str | None, message: str) -> SchemaIssue:
    return SchemaIssue(
        severity=severity,
        drift_type=drift_type,
        column_name=column_name,
        message=message,
    )


def _load_pandera():
    try:
        import pandera.pandas as pa

        return pa, None
    except ModuleNotFoundError:
        try:
            import pandera as pa

            return pa, None
        except ModuleNotFoundError as exc:
            return None, exc


def _pandera_dtype(pa, data_type: str) -> Any:
    return {
        "string": pa.String,
        "numeric": pa.Float,
        "integer": pa.Int,
        "boolean": pa.Bool,
        "datetime": pa.DateTime,
        "object": pa.Object,
    }[data_type]


def _build_checks(pa, rule: PanderaColumnRule) -> list[Any]:
    checks: list[Any] = []
    if rule.min is not None:
        checks.append(pa.Check.ge(rule.min))
    if rule.max is not None:
        checks.append(pa.Check.le(rule.max))
    if rule.regex:
        checks.append(pa.Check.str_matches(rule.regex))
    if rule.allowed_values:
        checks.append(pa.Check.isin(rule.allowed_values))
    return checks


def build_pandera_schema(table_name: str, path: str | Path = DEFAULT_CONTRACT_PATH):
    """Membangun DataFrameSchema Pandera dari contract YAML."""

    pa, import_error = _load_pandera()
    if import_error:
        raise import_error

    contract = get_contract(table_name, path)
    columns = {
        column_name: pa.Column(
            _pandera_dtype(pa, rule.type),
            checks=_build_checks(pa, rule),
            nullable=rule.nullable,
            coerce=rule.coerce,
            required=False,
        )
        for column_name, rule in contract.pandera.checks.items()
    }
    return pa.DataFrameSchema(columns=columns, strict=False, coerce=False)


def validate_dataframe_values_with_pandera(
    df,
    table_name: str,
    path: str | Path = DEFAULT_CONTRACT_PATH,
) -> list[SchemaIssue]:
    """
    Memvalidasi isi DataFrame dengan Pandera berdasarkan rule di YAML.

    Fungsi ini hanya menjalankan value-level checks. Schema drift level kolom
    tetap ditangani oleh validate_dataframe_schema().
    """

    contract = get_contract(table_name, path)
    if not contract.pandera.checks:
        return []

    pa, import_error = _load_pandera()
    if import_error:
        return [
            _issue(
                "WARNING",
                "pandera_dependency_missing",
                None,
                "Pandera belum terinstall, sehingga validasi value-level dilewati.",
            )
        ]

    schema = build_pandera_schema(table_name, path)
    try:
        schema.validate(df, lazy=True)
        return []
    except Exception as exc:
        issues: list[SchemaIssue] = []
        failure_cases = getattr(exc, "failure_cases", None)

        if failure_cases is not None and not failure_cases.empty:
            issue_rows = failure_cases.head(20).to_dict("records")
            seen_failures: set[tuple[str | None, str]] = set()
            for row in issue_rows:
                column_name = row.get("column")
                check_name = row.get("check")
                failure_case = row.get("failure_case")
                failure_key = (column_name, str(failure_case))
                if failure_key in seen_failures:
                    continue
                seen_failures.add(failure_key)
                rule = contract.pandera.checks.get(column_name)
                severity = rule.severity if rule else "WARNING"
                issues.append(
                    _issue(
                        severity,
                        "pandera_value_check_failed",
                        column_name,
                        f"Validasi Pandera gagal pada check '{check_name}' dengan nilai contoh '{failure_case}'.",
                    )
                )
            return issues

        return [
            _issue(
                "WARNING",
                "pandera_validation_failed",
                None,
                f"Validasi Pandera gagal: {exc}",
            )
        ]
