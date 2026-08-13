"""Filename and folder path parsing for marketplace files."""

from __future__ import annotations

from pathlib import Path
import re

from scripts.config import (
    MARKETPLACE_FOLDER_ALIASES,
    PHASE_FOLDER_ALIASES,
    SUPPORTED_MARKETPLACES,
    SUPPORTED_PHASES,
)
from scripts.discovery.models import MarketplaceFile
from scripts.discovery.stores import display_store_name


STANDARD_FILENAME_RE = re.compile(
    r"^(?P<marketplace>shopee|lazada|tiktok_tokopedia)_"
    r"(?P<phase>income|order|orders|report)_"
    r"(?P<store_slug>.+)_"
    r"(?P<start_date>\d{8})_"
    r"(?P<end_date>\d{8})"
    r"(?:_(?:part\d+|dup\d+))?$"
)

MONTH_NAMES = [
    "januari",
    "februari",
    "maret",
    "april",
    "mei",
    "juni",
    "juli",
    "agustus",
    "september",
    "oktober",
    "november",
    "desember",
]


def normalize_marketplace(value: str) -> str | None:
    return MARKETPLACE_FOLDER_ALIASES.get(value.lower())


def normalize_phase(value: str) -> str | None:
    return PHASE_FOLDER_ALIASES.get(value.lower())


def parse_standard_filename(path: Path) -> dict[str, str] | None:
    match = STANDARD_FILENAME_RE.match(path.stem)
    if not match:
        return None

    metadata = match.groupdict()
    metadata["phase"] = normalize_phase(metadata["phase"]) or metadata["phase"]
    metadata["store_name"] = display_store_name(metadata["marketplace"], metadata["store_slug"])
    return metadata


def parse_fixed_data_path(path: Path, source_root: Path) -> MarketplaceFile | None:
    try:
        relative_parts = path.relative_to(source_root).parts
    except ValueError:
        return None

    if len(relative_parts) < 3:
        return None

    marketplace = normalize_marketplace(relative_parts[0])
    phase = normalize_phase(relative_parts[1])
    if marketplace not in SUPPORTED_MARKETPLACES or phase not in SUPPORTED_PHASES:
        return None

    filename_metadata = parse_standard_filename(path) or {}
    if filename_metadata:
        marketplace = filename_metadata["marketplace"]
        phase = filename_metadata["phase"]

    partition_store_slug = None
    for part in relative_parts:
        if part.startswith("store="):
            partition_store_slug = part.split("=", 1)[1]
            marketplace_prefix = f"{marketplace}_"
            if partition_store_slug.startswith(marketplace_prefix):
                partition_store_slug = partition_store_slug[len(marketplace_prefix):]
            break

    store_slug = partition_store_slug or filename_metadata.get("store_slug")
    store_name = None
    if partition_store_slug:
        store_name = display_store_name(marketplace, partition_store_slug)
    else:
        store_name = filename_metadata.get("store_name")
    if not store_name and store_slug:
        store_name = display_store_name(marketplace, store_slug)

    year = relative_parts[2] if len(relative_parts) >= 4 else None
    month = relative_parts[3] if len(relative_parts) >= 5 else None

    return MarketplaceFile(
        path=path,
        marketplace=marketplace,
        phase=phase,
        year=year,
        month=month,
        store_slug=store_slug,
        store_name=store_name,
        start_date=filename_metadata.get("start_date"),
        end_date=filename_metadata.get("end_date"),
    )


def path_mentions_marketplace(path: Path, marketplace: str) -> bool:
    path_text = str(path).lower().replace("_", "-")
    if marketplace == "tiktok_tokopedia":
        return "tiktok" in path_text or "tokopedia" in path_text
    return marketplace.replace("_", "-") in path_text


def path_mentions_phase(path: Path, phase: str) -> bool:
    return phase.lower() in str(path).lower()


def infer_year(path: Path) -> str | None:
    match = re.search(r"\b(20\d{2})\b", str(path))
    return match.group(1) if match else None


def infer_month(path: Path) -> str | None:
    path_text = str(path).lower()
    for month in MONTH_NAMES:
        if month in path_text:
            return month
    return None


def infer_file_from_path(
    path: Path,
    *,
    marketplace: str | None,
    phase: str | None,
) -> MarketplaceFile | None:
    if not marketplace or not phase:
        return None
    if not path_mentions_marketplace(path, marketplace):
        return None
    if not path_mentions_phase(path, phase):
        return None

    filename_metadata = parse_standard_filename(path) or {}

    return MarketplaceFile(
        path=path,
        marketplace=marketplace,
        phase=phase,
        year=infer_year(path),
        month=infer_month(path),
        store_slug=filename_metadata.get("store_slug"),
        store_name=filename_metadata.get("store_name") if filename_metadata else None,
        start_date=filename_metadata.get("start_date") if filename_metadata else None,
        end_date=filename_metadata.get("end_date") if filename_metadata else None,
    )
