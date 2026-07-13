"""Filesystem scanner for marketplace import files."""

from __future__ import annotations

from pathlib import Path

from scripts.config import DEFAULT_SOURCE_ROOT, SUPPORTED_EXTENSIONS
from scripts.discovery.models import MarketplaceFile
from scripts.discovery.parsing import (
    infer_file_from_path,
    normalize_marketplace,
    normalize_phase,
    parse_fixed_data_path,
)


def is_supported_file(path: Path) -> bool:
    name = path.name
    if not path.is_file():
        return False
    if name.startswith("~$") or name.startswith(".~") or name.startswith("."):
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def discover_files(
    source_root: str | Path = DEFAULT_SOURCE_ROOT,
    *,
    marketplace: str | None = None,
    phase: str | None = None,
) -> list[MarketplaceFile]:
    root = Path(source_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Source root not found: {root}")

    normalized_marketplace = normalize_marketplace(marketplace) if marketplace else None
    normalized_phase = normalize_phase(phase) if phase else None

    files: list[MarketplaceFile] = []
    for path in root.rglob("*"):
        if not is_supported_file(path):
            continue

        item = parse_fixed_data_path(path, root)
        if item is None:
            item = infer_file_from_path(
                path,
                marketplace=normalized_marketplace,
                phase=normalized_phase,
            )
            if item is None:
                continue
        if normalized_marketplace and item.marketplace != normalized_marketplace:
            continue
        if normalized_phase and item.phase != normalized_phase:
            continue

        files.append(item)

    return sorted(files, key=lambda item: (item.marketplace, item.phase, str(item.path)))

