"""File-system staging helpers for marketplace sales uploads.

Raw uploaded files live on disk. PostgreSQL only stores a lightweight
manifest so the UI and transform step can audit what happened.
"""

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from src.db_config import logger
from src.file_inspector import count_rows_in_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGING_ROOT = PROJECT_ROOT / "data" / "staging" / "sales_online"
STAGING_ROOT = Path(os.getenv("SALES_ONLINE_FILE_STAGING_ROOT", DEFAULT_STAGING_ROOT))


@dataclass(frozen=True)
class FileUploadMetadata:
    fase: str
    marketplace: str
    marketplace_label: str
    store_name: str


def ensure_file_staging_tables(engine):
    """Ensure manifest and transform job tables exist with the columns we use."""
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staging.file_manifest (
                manifest_id       BIGSERIAL PRIMARY KEY,
                source_system     TEXT NOT NULL DEFAULT 'sales_online',
                marketplace       TEXT NOT NULL,
                fase              TEXT NOT NULL,
                store_name        TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                staged_filename   TEXT NOT NULL,
                file_path         TEXT NOT NULL UNIQUE,
                file_ext          TEXT,
                file_size_bytes   BIGINT,
                checksum_sha256   TEXT,
                rows_detected     INTEGER,
                file_status       TEXT NOT NULL DEFAULT 'staged',
                transform_status  TEXT NOT NULL DEFAULT 'pending',
                uploaded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                checked_at        TIMESTAMPTZ,
                transformed_at    TIMESTAMPTZ,
                error_message     TEXT
            )
        """))
        conn.execute(text("""
            ALTER TABLE staging.file_manifest
                ADD COLUMN IF NOT EXISTS source_system TEXT NOT NULL DEFAULT 'sales_online',
                ADD COLUMN IF NOT EXISTS marketplace TEXT,
                ADD COLUMN IF NOT EXISTS fase TEXT,
                ADD COLUMN IF NOT EXISTS store_name TEXT,
                ADD COLUMN IF NOT EXISTS original_filename TEXT,
                ADD COLUMN IF NOT EXISTS staged_filename TEXT,
                ADD COLUMN IF NOT EXISTS file_path TEXT,
                ADD COLUMN IF NOT EXISTS file_ext TEXT,
                ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT,
                ADD COLUMN IF NOT EXISTS checksum_sha256 TEXT,
                ADD COLUMN IF NOT EXISTS rows_detected INTEGER,
                ADD COLUMN IF NOT EXISTS file_status TEXT NOT NULL DEFAULT 'staged',
                ADD COLUMN IF NOT EXISTS transform_status TEXT NOT NULL DEFAULT 'pending',
                ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS checked_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS transformed_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS error_message TEXT
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_file_manifest_sales_lookup
            ON staging.file_manifest (
                source_system,
                marketplace,
                fase,
                store_name,
                original_filename
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_file_manifest_transform_status
            ON staging.file_manifest (source_system, transform_status, marketplace)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staging.transform_job_log (
                job_id              BIGSERIAL PRIMARY KEY,
                job_type            TEXT NOT NULL,
                marketplace         TEXT,
                fase                TEXT,
                status              TEXT NOT NULL DEFAULT 'pending',
                source_filenames    JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_manifest_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at          TIMESTAMPTZ,
                finished_at         TIMESTAMPTZ,
                error_message       TEXT
            )
        """))
        conn.execute(text("""
            ALTER TABLE staging.transform_job_log
                ADD COLUMN IF NOT EXISTS source_manifest_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                ADD COLUMN IF NOT EXISTS source_filenames JSONB NOT NULL DEFAULT '[]'::jsonb,
                ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS error_message TEXT
        """))


def slugify(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "unknown"


def calculate_sha256(file_path):
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_path(path):
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_dup{counter:02d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def build_staging_path(original_filename, metadata: FileUploadMetadata, uploaded_at=None):
    uploaded_at = uploaded_at or datetime.now()
    file_ext = Path(original_filename).suffix.lower() or ".xlsx"
    original_stem = slugify(Path(original_filename).stem)
    marketplace = slugify(metadata.marketplace)
    fase = slugify(metadata.fase)
    store = slugify(metadata.store_name)

    folder = (
        STAGING_ROOT
        / marketplace
        / fase
        / f"store={store}"
        / f"uploaded_date={uploaded_at:%Y-%m-%d}"
    )
    folder.mkdir(parents=True, exist_ok=True)

    staged_name = f"{marketplace}_{fase}_{store}__{original_stem}{file_ext}"
    return _unique_path(folder / staged_name)


def check_file_manifest_status(filename, file_path, metadata: FileUploadMetadata, engine):
    """Check whether an uploaded file already exists in the file manifest."""
    ensure_file_staging_tables(engine)
    rows_in_file = count_rows_in_file(file_path, metadata.fase, metadata.marketplace)
    checksum = calculate_sha256(file_path)
    file_size = Path(file_path).stat().st_size

    with engine.connect() as conn:
        same_checksum = conn.execute(text("""
            SELECT rows_detected
            FROM staging.file_manifest
            WHERE source_system = 'sales_online'
              AND marketplace = :marketplace
              AND fase = :fase
              AND store_name = :store_name
              AND checksum_sha256 = :checksum
              AND file_status <> 'invalid'
            ORDER BY uploaded_at DESC
            LIMIT 1
        """), {
            "marketplace": metadata.marketplace,
            "fase": metadata.fase,
            "store_name": metadata.store_name,
            "checksum": checksum,
        }).first()

        same_identity = conn.execute(text("""
            SELECT rows_detected, checksum_sha256
            FROM staging.file_manifest
            WHERE source_system = 'sales_online'
              AND marketplace = :marketplace
              AND fase = :fase
              AND store_name = :store_name
              AND original_filename = :filename
              AND file_status <> 'invalid'
            ORDER BY uploaded_at DESC
            LIMIT 1
        """), {
            "marketplace": metadata.marketplace,
            "fase": metadata.fase,
            "store_name": metadata.store_name,
            "filename": filename,
        }).first()

    if same_checksum:
        status = "fully_loaded"
        rows_recorded = int(same_checksum.rows_detected or 0)
    elif same_identity:
        rows_recorded = int(same_identity.rows_detected or 0)
        if rows_recorded < rows_in_file:
            status = "partial"
        else:
            status = "anomaly"
    else:
        status = "new"
        rows_recorded = 0

    return {
        "status": status,
        "rows_in_db": rows_recorded,
        "rows_in_file": rows_in_file,
        "checksum_sha256": checksum,
        "file_size_bytes": file_size,
        "table": "staging.file_manifest",
    }


def stage_uploaded_file(uploaded_file, metadata: FileUploadMetadata, engine):
    """Write uploaded file to filesystem and insert a manifest row."""
    ensure_file_staging_tables(engine)
    staged_path = build_staging_path(uploaded_file.name, metadata)

    with open(staged_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    rows_detected = count_rows_in_file(str(staged_path), metadata.fase, metadata.marketplace)
    checksum = calculate_sha256(staged_path)
    file_size = staged_path.stat().st_size

    with engine.begin() as conn:
        manifest_id = conn.execute(text("""
            INSERT INTO staging.file_manifest (
                source_system,
                marketplace,
                fase,
                store_name,
                original_filename,
                staged_filename,
                file_path,
                file_ext,
                file_size_bytes,
                checksum_sha256,
                rows_detected,
                file_status,
                transform_status,
                checked_at
            )
            VALUES (
                'sales_online',
                :marketplace,
                :fase,
                :store_name,
                :original_filename,
                :staged_filename,
                :file_path,
                :file_ext,
                :file_size_bytes,
                :checksum_sha256,
                :rows_detected,
                'staged',
                'pending',
                NOW()
            )
            RETURNING manifest_id
        """), {
            "marketplace": metadata.marketplace,
            "fase": metadata.fase,
            "store_name": metadata.store_name,
            "original_filename": uploaded_file.name,
            "staged_filename": staged_path.name,
            "file_path": str(staged_path),
            "file_ext": staged_path.suffix.lower(),
            "file_size_bytes": file_size,
            "checksum_sha256": checksum,
            "rows_detected": rows_detected,
        }).scalar_one()

    logger.info(
        "File staged: %s -> %s [manifest_id=%s]",
        uploaded_file.name,
        staged_path,
        manifest_id,
    )
    return {
        "manifest_id": int(manifest_id),
        "staged_filename": staged_path.name,
        "file_path": str(staged_path),
        "rows_detected": rows_detected,
    }


def get_manifest_rows(engine, manifest_ids):
    if not manifest_ids:
        return []
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                manifest_id,
                marketplace,
                fase,
                store_name,
                staged_filename,
                original_filename,
                file_path,
                transform_status
            FROM staging.file_manifest
            WHERE manifest_id = ANY(:manifest_ids)
            ORDER BY manifest_id
        """), {"manifest_ids": manifest_ids})
        return [dict(r._mapping) for r in result]


def set_manifest_transform_status(engine, manifest_ids, status, file_status=None, error_message=None):
    if not manifest_ids:
        return
    assignments = [
        "transform_status = :status",
        "error_message = :error_message",
    ]
    if status in {"success", "failed"}:
        assignments.append("transformed_at = NOW()")
    if file_status:
        assignments.append("file_status = :file_status")

    with engine.begin() as conn:
        conn.execute(text(f"""
            UPDATE staging.file_manifest
            SET {', '.join(assignments)}
            WHERE manifest_id = ANY(:manifest_ids)
        """), {
            "manifest_ids": manifest_ids,
            "status": status,
            "file_status": file_status,
            "error_message": error_message,
        })


def parse_manifest_ids(value):
    if isinstance(value, list):
        return [int(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return [int(v) for v in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []
