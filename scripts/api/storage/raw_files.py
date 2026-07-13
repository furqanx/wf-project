"""Helpers for writing raw API responses to filesystem storage."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.api.models import EndpointSpec, RawFileInfo


def write_raw_response(
    *,
    raw_root: str | Path,
    spec: EndpointSpec,
    fetched_at: datetime,
    responses: list[dict[str, Any]],
    compress: bool = False,
) -> RawFileInfo:
    """Write one endpoint fetch result to a dated raw-data folder."""
    fetched_date = fetched_at.date().isoformat()
    output_dir = Path(raw_root) / spec.endpoint_group / f"fetched_date={fetched_date}"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = fetched_at.strftime("%Y%m%d_%H%M%S")
    is_jsonl = len(responses) > 1
    suffix = ".jsonl" if is_jsonl else ".json"
    if compress:
        suffix = f"{suffix}.gz"

    file_name = f"{spec.file_prefix}_{timestamp}{suffix}"
    output_path = output_dir / file_name

    if is_jsonl:
        content = "\n".join(json.dumps(response, ensure_ascii=False) for response in responses)
    else:
        content = json.dumps(responses[0] if responses else {}, ensure_ascii=False, indent=2)

    if compress:
        with gzip.open(output_path, "wt", encoding="utf-8") as f:
            f.write(content)
    else:
        output_path.write_text(content, encoding="utf-8")

    return RawFileInfo(
        storage_path=output_dir,
        file_name=file_name,
        file_format="jsonl" if is_jsonl else "json",
        is_compressed=compress,
        file_size_bytes=output_path.stat().st_size,
        checksum_sha256=sha256_file(output_path),
        record_count=sum(count_records(response) for response in responses),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_records(response: dict[str, Any]) -> int:
    data = response.get("data")
    if isinstance(data, dict):
        for key in ("items", "lists", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
        return 1 if data else 0
    if isinstance(data, list):
        return len(data)
    return 1 if response else 0
