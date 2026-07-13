"""Discovery data models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MarketplaceFile:
    path: Path
    marketplace: str
    phase: str
    year: str | None = None
    month: str | None = None
    store_slug: str | None = None
    store_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()

