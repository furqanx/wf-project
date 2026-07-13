"""Helpers for diffing indexed master-data snapshots."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine


SNAPSHOT_SCHEMA = "api_staging"
SNAPSHOT_INDEX_TABLE = "master_snapshot_index"
SNAPSHOT_DIFF_TABLE = "master_snapshot_diff"
BUSINESS_KEY_FIELDS = ("id", "no", "number", "code", "name")


def process_pending_master_snapshot_diffs(
    engine: Engine,
    *,
    source_system: str = "accurate",
    entity_name: str | None = None,
    run_id: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Compare pending master snapshots with their previous snapshot."""
    pending = fetch_pending_snapshots(
        engine,
        source_system=source_system,
        entity_name=entity_name,
        limit=limit,
    )
    summary = {
        "pending_snapshot_count": len(pending),
        "processed_snapshot_count": 0,
        "skipped_snapshot_count": 0,
        "inserted_diff_count": 0,
        "deleted_diff_count": 0,
        "total_diff_count": 0,
    }

    for current in pending:
        previous = fetch_previous_snapshot(engine, current)
        if previous is None:
            mark_snapshot_processed(engine, int(current["snapshot_id"]))
            summary["processed_snapshot_count"] += 1
            summary["skipped_snapshot_count"] += 1
            continue

        diffs = diff_snapshot_files(
            previous_file_path=str(previous["file_path"]),
            current_file_path=str(current["file_path"]),
            source_system=str(current["source_system"]),
            entity_name=str(current["entity_name"]),
            previous_snapshot_date=previous["snapshot_date"],
            current_snapshot_date=current["snapshot_date"],
            run_id=run_id or current.get("run_id"),
        )
        diff_type_counts = count_diff_types(diffs)
        inserted_count = insert_master_snapshot_diffs(engine, diffs)
        mark_snapshot_processed(engine, int(current["snapshot_id"]))
        summary["processed_snapshot_count"] += 1
        summary["inserted_diff_count"] += diff_type_counts["inserted"]
        summary["deleted_diff_count"] += diff_type_counts["deleted"]
        summary["total_diff_count"] += inserted_count

    return summary


def fetch_pending_snapshots(
    engine: Engine,
    *,
    source_system: str,
    entity_name: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            idx.snapshot_id,
            idx.source_system,
            idx.entity_name,
            idx.snapshot_date,
            idx.file_path,
            idx.record_count,
            m.run_id
        FROM {SNAPSHOT_SCHEMA}.{SNAPSHOT_INDEX_TABLE} idx
        LEFT JOIN {SNAPSHOT_SCHEMA}.raw_file_manifest m
            ON m.manifest_id = idx.manifest_id
        WHERE idx.source_system = :source_system
          AND idx.processed_for_diff = false
          {"AND idx.entity_name = :entity_name" if entity_name else ""}
        ORDER BY idx.snapshot_date, idx.snapshot_id
        {"LIMIT :limit" if limit else ""}
    """
    params: dict[str, Any] = {"source_system": source_system}
    if entity_name:
        params["entity_name"] = entity_name
    if limit:
        params["limit"] = limit
    with engine.connect() as conn:
        return list(conn.execute(text(query), params).mappings())


def fetch_previous_snapshot(engine: Engine, current: dict[str, Any]) -> dict[str, Any] | None:
    query = text(
        f"""
        SELECT
            snapshot_id,
            source_system,
            entity_name,
            snapshot_date,
            file_path,
            record_count
        FROM {SNAPSHOT_SCHEMA}.{SNAPSHOT_INDEX_TABLE}
        WHERE source_system = :source_system
          AND entity_name = :entity_name
          AND snapshot_date < :snapshot_date
        ORDER BY snapshot_date DESC, snapshot_id DESC
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        row = conn.execute(
            query,
            {
                "source_system": current["source_system"],
                "entity_name": current["entity_name"],
                "snapshot_date": current["snapshot_date"],
            },
        ).mappings().first()
    return dict(row) if row else None


def diff_snapshot_files(
    *,
    previous_file_path: str,
    current_file_path: str,
    source_system: str,
    entity_name: str,
    previous_snapshot_date: Any,
    current_snapshot_date: Any,
    run_id: str | None,
) -> list[dict[str, Any]]:
    previous_records = records_by_business_key(load_raw_records(previous_file_path))
    current_records = records_by_business_key(load_raw_records(current_file_path))

    diffs: list[dict[str, Any]] = []
    previous_keys = set(previous_records)
    current_keys = set(current_records)

    for key in sorted(current_keys - previous_keys):
        current = current_records[key]
        diffs.append(
            build_diff_payload(
                source_system=source_system,
                entity_name=entity_name,
                business_key=key,
                diff_type="inserted",
                previous_snapshot_date=previous_snapshot_date,
                current_snapshot_date=current_snapshot_date,
                changed_fields=["*"],
                previous_values=None,
                current_values=current,
                run_id=run_id,
            )
        )

    for key in sorted(previous_keys - current_keys):
        previous = previous_records[key]
        diffs.append(
            build_diff_payload(
                source_system=source_system,
                entity_name=entity_name,
                business_key=key,
                diff_type="deleted",
                previous_snapshot_date=previous_snapshot_date,
                current_snapshot_date=current_snapshot_date,
                changed_fields=["*"],
                previous_values=previous,
                current_values=None,
                run_id=run_id,
            )
        )

    return diffs


def load_raw_records(file_path: str) -> list[dict[str, Any]]:
    path = Path(file_path)
    payloads = load_raw_payloads(path)
    records: list[dict[str, Any]] = []
    for payload in payloads:
        if isinstance(payload, dict) and payload.get("s") is False:
            raise RuntimeError(f"Raw snapshot response is unsuccessful: {file_path}")
        records.extend(extract_records(payload))
    return records


def load_raw_payloads(path: Path) -> list[Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            content = f.read()
    else:
        content = path.read_text(encoding="utf-8")

    if ".jsonl" in path.name:
        return [json.loads(line) for line in content.splitlines() if line.strip()]
    return [json.loads(content)]


def extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("d", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
            if isinstance(value, dict):
                return [value]
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    return []


def records_by_business_key(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        business_key = get_business_key(record)
        if business_key in result:
            raise ValueError(f"Duplicate business key found in snapshot: {business_key}")
        result[business_key] = record
    return result


def get_business_key(record: dict[str, Any]) -> str:
    for field in BUSINESS_KEY_FIELDS:
        value = record.get(field)
        if value not in (None, ""):
            return str(value)
    return stable_record_hash(record)


def normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    return value


def stable_record_hash(record: dict[str, Any]) -> str:
    raw = json.dumps(normalize_value(record), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_diff_payload(
    *,
    source_system: str,
    entity_name: str,
    business_key: str,
    diff_type: str,
    previous_snapshot_date: Any,
    current_snapshot_date: Any,
    changed_fields: list[str],
    previous_values: dict[str, Any] | None,
    current_values: dict[str, Any] | None,
    run_id: str | None,
) -> dict[str, Any]:
    return {
        "source_system": source_system,
        "entity_name": entity_name,
        "business_key": business_key,
        "diff_type": diff_type,
        "previous_snapshot_date": previous_snapshot_date,
        "current_snapshot_date": current_snapshot_date,
        "changed_fields": json.dumps(changed_fields, ensure_ascii=False),
        "previous_values": json.dumps(previous_values, ensure_ascii=False, default=str)
        if previous_values is not None
        else None,
        "current_values": json.dumps(current_values, ensure_ascii=False, default=str)
        if current_values is not None
        else None,
        "run_id": run_id,
    }


def insert_master_snapshot_diffs(engine: Engine, diffs: list[dict[str, Any]]) -> int:
    if not diffs:
        return 0
    query = text(
        f"""
        INSERT INTO {SNAPSHOT_SCHEMA}.{SNAPSHOT_DIFF_TABLE} (
            source_system,
            entity_name,
            business_key,
            diff_type,
            previous_snapshot_date,
            current_snapshot_date,
            changed_fields,
            previous_values,
            current_values,
            run_id
        )
        VALUES (
            :source_system,
            :entity_name,
            :business_key,
            :diff_type,
            :previous_snapshot_date,
            :current_snapshot_date,
            CAST(:changed_fields AS jsonb),
            CAST(:previous_values AS jsonb),
            CAST(:current_values AS jsonb),
            :run_id
        )
        """
    )
    with engine.begin() as conn:
        conn.execute(query, diffs)
    return len(diffs)


def count_diff_types(diffs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "inserted": sum(1 for diff in diffs if diff["diff_type"] == "inserted"),
        "deleted": sum(1 for diff in diffs if diff["diff_type"] == "deleted"),
    }


def mark_snapshot_processed(engine: Engine, snapshot_id: int) -> None:
    query = text(
        f"""
        UPDATE {SNAPSHOT_SCHEMA}.{SNAPSHOT_INDEX_TABLE}
        SET processed_for_diff = true,
            processed_at = now()
        WHERE snapshot_id = :snapshot_id
        """
    )
    with engine.begin() as conn:
        conn.execute(query, {"snapshot_id": snapshot_id})
