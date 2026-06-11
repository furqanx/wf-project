from functools import lru_cache
from pathlib import Path
import re
from collections import Counter

import yaml

from src.schema_contracts.models import (
    DefaultMode,
    SchemaContractsConfig,
    SchemaIssue,
    SchemaValidationResult,
    TableSchemaContract,
)


DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "config" / "schema_contracts.yml"


@lru_cache(maxsize=1)
def load_contracts(path: str | Path = DEFAULT_CONTRACT_PATH) -> SchemaContractsConfig:
    """Membaca dan memvalidasi schema contract YAML dengan Pydantic."""

    contract_path = Path(path)
    raw_config = yaml.safe_load(contract_path.read_text()) or {}
    return SchemaContractsConfig.model_validate(raw_config)


def get_contract(table_name: str, path: str | Path = DEFAULT_CONTRACT_PATH) -> TableSchemaContract:
    """Mengambil contract berdasarkan nama tabel staging."""

    config = load_contracts(path)
    try:
        return config.contracts[table_name]
    except KeyError as exc:
        raise KeyError(f"Schema contract tidak ditemukan untuk tabel: {table_name}") from exc


def get_effective_mode(table_name: str, path: str | Path = DEFAULT_CONTRACT_PATH) -> DefaultMode:
    """Mengambil mode validasi final setelah mempertimbangkan default config."""

    config = load_contracts(path)
    contract = get_contract(table_name, path)
    if contract.mode == "inherit":
        return config.default_mode
    return contract.mode




def normalize_column_name(column_name: object) -> str:
    """Menormalkan nama kolom tanpa mengubah makna bisnisnya."""

    normalized = str(column_name)
    normalized = normalized.replace("\ufeff", "")
    normalized = normalized.replace("\u00a0", " ")
    normalized = re.sub(r"[\r\n\t]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _build_alias_map(contract: TableSchemaContract) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for source_column, target_column in contract.aliases.items():
        aliases[source_column] = target_column
        aliases[normalize_column_name(source_column)] = target_column
    return aliases


def _issue(severity: str, drift_type: str, column_name: str | None, message: str) -> SchemaIssue:
    return SchemaIssue(
        severity=severity,
        drift_type=drift_type,
        column_name=column_name,
        message=message,
    )




def validate_dataframe_schema(
    df,
    table_name: str,
    path: str | Path = DEFAULT_CONTRACT_PATH,
) -> SchemaValidationResult:
    """
    Memvalidasi schema DataFrame terhadap contract tabel staging.

    Fungsi ini belum melakukan validasi tipe/nilai isi sel. Fokusnya adalah
    schema drift level kolom: normalisasi nama kolom, alias, missing column,
    extra column, deprecated column, ignored column, dan konflik hasil rename.
    """

    contract = get_contract(table_name, path)
    effective_mode = get_effective_mode(table_name, path)
    alias_map = _build_alias_map(contract)

    normalized_df = df.copy()
    original_columns = [str(column) for column in normalized_df.columns]

    final_columns: list[str] = []
    renamed_columns: dict[str, str] = {}
    issues: list[SchemaIssue] = []

    for original_column in original_columns:
        normalized_column = normalize_column_name(original_column)
        final_column = alias_map.get(original_column, alias_map.get(normalized_column, normalized_column))

        if original_column != final_column:
            renamed_columns[original_column] = final_column
            drift_type = "alias_column" if final_column != normalized_column else "normalized_column_name"
            issues.append(
                _issue(
                    "INFO",
                    drift_type,
                    original_column,
                    f"Kolom '{original_column}' dinormalisasi/direname menjadi '{final_column}'.",
                )
            )

        final_columns.append(final_column)

    duplicate_columns = sorted(column for column, count in Counter(final_columns).items() if count > 1)
    for column in duplicate_columns:
        issues.append(
            _issue(
                "ERROR",
                "duplicate_column_after_normalization",
                column,
                f"Lebih dari satu kolom menjadi '{column}' setelah normalisasi/alias. Mapping ambigu.",
            )
        )

    normalized_df.columns = final_columns

    current_columns = set(final_columns)
    allowed_columns = set(contract.allowed_columns)
    required_columns = set(contract.required_columns)
    optional_columns = set(contract.optional_columns)
    deprecated_columns_set = set(contract.deprecated_columns)
    ignored_columns_set = set(contract.ignored_columns)

    missing_required_columns = sorted(required_columns - current_columns)
    missing_optional_columns = sorted(optional_columns - current_columns)
    deprecated_columns = sorted(current_columns & deprecated_columns_set)
    ignored_columns = sorted(current_columns & ignored_columns_set)
    extra_columns = sorted(current_columns - allowed_columns - ignored_columns_set)
    dropped_columns = sorted(set(extra_columns) | set(ignored_columns))

    for column in missing_required_columns:
        issues.append(
            _issue(
                "ERROR",
                "missing_required_column",
                column,
                f"Kolom wajib '{column}' tidak ditemukan pada file upload.",
            )
        )

    for column in missing_optional_columns:
        issues.append(
            _issue(
                "WARNING",
                "missing_optional_column",
                column,
                f"Kolom opsional '{column}' tidak ditemukan pada file upload.",
            )
        )

    for column in extra_columns:
        issues.append(
            _issue(
                "WARNING",
                "extra_column",
                column,
                f"Kolom '{column}' tidak ada di allowed_columns dan akan di-drop sebelum masuk staging.",
            )
        )

    for column in ignored_columns:
        issues.append(
            _issue(
                "INFO",
                "ignored_column",
                column,
                f"Kolom '{column}' diklasifikasikan sebagai ignored dan akan di-drop.",
            )
        )

    for column in deprecated_columns:
        issues.append(
            _issue(
                "WARNING",
                "deprecated_column",
                column,
                f"Kolom '{column}' sudah deprecated. Review apakah masih perlu dipakai.",
            )
        )

    if dropped_columns:
        normalized_df = normalized_df.drop(columns=dropped_columns, errors="ignore")

    has_errors = any(issue.severity == "ERROR" for issue in issues)
    has_ambiguous_columns = bool(duplicate_columns)
    can_continue = not has_ambiguous_columns and (effective_mode == "observe_only" or not has_errors)

    return SchemaValidationResult(
        table_name=table_name,
        effective_mode=effective_mode,
        can_continue=can_continue,
        normalized_df=normalized_df,
        original_columns=original_columns,
        normalized_columns=list(normalized_df.columns),
        dropped_columns=dropped_columns,
        renamed_columns=renamed_columns,
        missing_required_columns=missing_required_columns,
        missing_optional_columns=missing_optional_columns,
        extra_columns=extra_columns,
        deprecated_columns=deprecated_columns,
        ignored_columns=ignored_columns,
        issues=issues,
    )
