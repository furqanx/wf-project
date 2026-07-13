"""Helpers for writing raw API file metadata to PostgreSQL."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.api.models import ManifestRecord


MANIFEST_SCHEMA = "api_staging"
MANIFEST_TABLE = "raw_file_manifest"


def insert_manifest_record(
    engine: Engine,
    record: ManifestRecord,
    *,
    schema: str = MANIFEST_SCHEMA,
    table_name: str = MANIFEST_TABLE,
) -> None:
    query = text(
        f"""
        INSERT INTO {schema}.{table_name} (
            source_system,
            endpoint_group,
            endpoint,
            request_method,
            request_params,
            request_hash,
            fetched_at,
            fetched_date,
            storage_path,
            file_name,
            file_format,
            is_compressed,
            status_code,
            success,
            record_count,
            file_size_bytes,
            checksum_sha256,
            duration_ms,
            page_number,
            pagination_key,
            run_id,
            error_message
        )
        VALUES (
            :source_system,
            :endpoint_group,
            :endpoint,
            :request_method,
            CAST(:request_params AS jsonb),
            :request_hash,
            :fetched_at,
            :fetched_date,
            :storage_path,
            :file_name,
            :file_format,
            :is_compressed,
            :status_code,
            :success,
            :record_count,
            :file_size_bytes,
            :checksum_sha256,
            :duration_ms,
            :page_number,
            :pagination_key,
            :run_id,
            :error_message
        )
        """
    )
    payload = {
        "source_system": record.source_system,
        "endpoint_group": record.endpoint_group,
        "endpoint": record.endpoint,
        "request_method": record.request_method,
        "request_params": json.dumps(record.request_params, ensure_ascii=False),
        "request_hash": record.request_hash,
        "fetched_at": record.fetched_at,
        "fetched_date": record.fetched_date,
        "storage_path": record.storage_path,
        "file_name": record.file_name,
        "file_format": record.file_format,
        "is_compressed": record.is_compressed,
        "status_code": record.status_code,
        "success": record.success,
        "record_count": record.record_count,
        "file_size_bytes": record.file_size_bytes,
        "checksum_sha256": record.checksum_sha256,
        "duration_ms": record.duration_ms,
        "page_number": record.page_number,
        "pagination_key": record.pagination_key,
        "run_id": record.run_id,
        "error_message": record.error_message,
    }
    with engine.begin() as conn:
        conn.execute(query, payload)
