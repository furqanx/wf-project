"""Shared loader result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class LoadedFrame:
    table_name: str
    dataframe: pd.DataFrame
    source_path: Path
    sheet_name: str | None = None
    ignored_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.dataframe)

