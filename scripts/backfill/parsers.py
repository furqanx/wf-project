"""Path and filename parsers for backfilling filesystem staging files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from scripts.discovery.parsing import parse_fixed_data_path


CREWDIBLE_FILENAME_RE = re.compile(
    r"^crewdible_transaction_(?P<year>\d{4})(?:_(?P<month>\d{2}))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BackfillFile:
    source_path: Path
    source_system: str
    data_category: str
    marketplace: str
    fase: str
    store_name: str
    period_year: int | None
    period_month: int | None


def parse_crewdible_file(path: Path) -> BackfillFile | None:
    match = CREWDIBLE_FILENAME_RE.match(path.stem)
    if not match:
        return None

    month = match.group("month")
    return BackfillFile(
        source_path=path,
        source_system="crewdible",
        data_category="transaction",
        marketplace="crewdible",
        fase="TRANSACTION",
        store_name="crewdible",
        period_year=int(match.group("year")),
        period_month=int(month) if month else None,
    )


def parse_sales_online_file(path: Path, source_root: Path) -> BackfillFile | None:
    metadata = parse_fixed_data_path(path, source_root)
    if metadata is None or not metadata.store_name:
        return None

    period_year, period_month = _period_from_date_range(metadata.start_date, metadata.end_date)

    return BackfillFile(
        source_path=metadata.path,
        source_system="sales_online",
        data_category=metadata.phase,
        marketplace=metadata.marketplace,
        fase=metadata.phase.upper(),
        store_name=metadata.store_name,
        period_year=period_year,
        period_month=period_month,
    )


def _period_from_date_range(start_date: str | None, end_date: str | None) -> tuple[int | None, int | None]:
    if not start_date or not end_date or len(start_date) < 6 or len(end_date) < 6:
        return None, None

    start_year = int(start_date[:4])
    start_month = int(start_date[4:6])
    end_year = int(end_date[:4])
    end_month = int(end_date[4:6])

    if start_year != end_year:
        return start_year, None
    if start_month != end_month:
        return start_year, None
    return start_year, start_month
