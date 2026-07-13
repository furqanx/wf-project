"""Compatibility wrapper for marketplace file discovery."""

from __future__ import annotations

from scripts.discovery import MarketplaceFile, discover_files
from scripts.discovery.files import is_supported_file
from scripts.discovery.parsing import (
    infer_file_from_path,
    infer_month,
    infer_year,
    normalize_marketplace,
    normalize_phase,
    parse_fixed_data_path,
    parse_standard_filename,
    path_mentions_marketplace,
    path_mentions_phase,
)
from scripts.discovery.stores import STORE_NAME_BY_MARKETPLACE_AND_SLUG, display_store_name

__all__ = [
    "MarketplaceFile",
    "STORE_NAME_BY_MARKETPLACE_AND_SLUG",
    "discover_files",
    "display_store_name",
    "infer_file_from_path",
    "infer_month",
    "infer_year",
    "is_supported_file",
    "normalize_marketplace",
    "normalize_phase",
    "parse_fixed_data_path",
    "parse_standard_filename",
    "path_mentions_marketplace",
    "path_mentions_phase",
]
