"""Shared configuration for marketplace staging imports."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "data"

TARGET_SCHEMA   = os.getenv("TARGET_SCHEMA", "public_staging")
DEFAULT_DB_NAME = os.getenv("IMPORT_DB_NAME", os.getenv("DB_NAME", "wellfarm_alternatives"))

SUPPORTED_EXTENSIONS   = {".xlsx", ".xls", ".csv"}
SUPPORTED_MARKETPLACES = {"shopee", "tiktok_tokopedia", "lazada"}
SUPPORTED_PHASES       = {"income", "order", "report"}

MARKETPLACE_FOLDER_ALIASES = {
    "shopee": "shopee",
    "lazada": "lazada",
    "tiktok-tokopedia": "tiktok_tokopedia",
    "tiktok_tokopedia": "tiktok_tokopedia",
}

PHASE_FOLDER_ALIASES = {
    "income"  : "income",
    "order"   : "order",
    "orders"  : "order",
    "report"  : "report",
    "reports" : "report",
}
