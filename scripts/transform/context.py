"""Shared transform configuration helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "scripts" / "transform" / "sql"


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class TransformContext:
    staging_schema: str = "public_staging"
    target_schema: str = "public"

    def validate(self) -> None:
        validate_identifier(self.staging_schema, "staging_schema")
        validate_identifier(self.target_schema, "target_schema")

    def render_sql(self, sql_name: str) -> str:
        self.validate()
        template = (SQL_DIR / sql_name).read_text(encoding="utf-8")
        return template.format(
            staging_schema=self.staging_schema,
            target_schema=self.target_schema,
        )


def validate_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier for {label}: {value!r}")

