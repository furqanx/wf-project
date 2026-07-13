"""Helpers for indexing master-data raw snapshots."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.api.models import ManifestRecord


SNAPSHOT_SCHEMA = "api_staging"
SNAPSHOT_INDEX_TABLE = "master_snapshot_index"


def insert_master_snapshot_indexes(
    engine: Engine,
    records: list[ManifestRecord],
    *,
    schema: str = SNAPSHOT_SCHEMA,
    table_name: str = SNAPSHOT_INDEX_TABLE,
) -> int:
    """Insert one snapshot-index row for each successful master snapshot file."""
    rows = [build_snapshot_index_payload(record) for record in records if should_index(record)]
    if not rows:
        return 0

    query = text(
        f"""
        INSERT INTO {schema}.{table_name} (
            source_system,
            entity_name,
            snapshot_date,
            manifest_id,
            file_path,
            record_count,
            processed_for_diff
        )
        VALUES (
            :source_system,
            :entity_name,
            :snapshot_date,
            :manifest_id,
            :file_path,
            :record_count,
            false
        )
        """
    )
    with engine.begin() as conn:
        conn.execute(query, rows)
    return len(rows)


def should_index(record: ManifestRecord) -> bool:
    return (
        record.success
        and record.source_system == "accurate"
        and record.endpoint_group == "master_data"
        and record.storage_path is not None
        and record.file_name is not None
    )


def build_snapshot_index_payload(record: ManifestRecord) -> dict[str, object]:
    return {
        "source_system": record.source_system,
        "entity_name": endpoint_to_entity_name(record.endpoint),
        "snapshot_date": record.fetched_date,
        "manifest_id": record.manifest_id,
        "file_path": str(Path(record.storage_path or "") / (record.file_name or "")),
        "record_count": record.record_count,
    }


def endpoint_to_entity_name(endpoint: str) -> str:
    """Convert /api/item-category to item_category."""
    normalized = endpoint.strip("/")
    if normalized.startswith("api/"):
        normalized = normalized.removeprefix("api/")
    return normalized.replace("/", "_").replace("-", "_")
