"""Small DataFrame normalization helpers for raw staging imports."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def clean_column_name(column: object) -> str:
    if column is None or pd.isna(column):
        return ""
    cleaned = str(column).strip()
    if cleaned.lower().startswith("unnamed:") or cleaned.lower() in {"none", "nan", "<na>"}:
        return ""
    return cleaned


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result.columns = [clean_column_name(col) for col in result.columns]
    result = result.loc[:, [col != "" for col in result.columns]]
    return result


def drop_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    result = df.replace({"": pd.NA, "None": pd.NA, "nan": pd.NA})
    return result.dropna(how="all").reset_index(drop=True)


def extract_store_name_from_filename(path: str | Path) -> str:
    stem = Path(path).stem.lower()
    parts = stem.split("_")
    if len(parts) >= 5 and parts[-1].isdigit() and parts[-2].isdigit():
        if parts[:2] == ["tiktok", "tokopedia"]:
            return " ".join(parts[3:-2])
        return " ".join(parts[2:-2])
    return " ".join(stem.replace("-", "_").split("_")) or Path(path).stem


def unique_values_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def prepare_raw_staging_frame(
    df: pd.DataFrame,
    *,
    column_map: dict[str, str],
    source_path: str | Path,
    include_store_name: bool = True,
    store_name: str | None = None,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Rename source columns, add metadata, and align to target staging columns."""
    result = normalize_columns(df)
    result = result.rename(columns=column_map)
    result = drop_empty_rows(result)

    source_path = Path(source_path)
    if include_store_name:
        result["store_name"] = store_name or extract_store_name_from_filename(source_path)
    result["source_filename"] = source_path.name

    target_columns = unique_values_in_order(list(column_map.values()))
    if include_store_name:
        target_columns.append("store_name")
    target_columns.append("source_filename")

    ignored_columns = [col for col in result.columns if col not in target_columns]
    missing_columns = [col for col in target_columns if col not in result.columns]

    for column in missing_columns:
        result[column] = pd.NA

    return result[target_columns], ignored_columns, missing_columns
