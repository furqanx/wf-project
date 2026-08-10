"""Shared helpers for filesystem-staged uploads and PostgreSQL manifests."""

import hashlib
import os
import re
from pathlib import Path

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def ensure_file_manifest_tables(engine):
    """Ensure common manifest tables exist for filesystem-staged files."""
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staging.file_manifest (
                manifest_id       BIGSERIAL PRIMARY KEY,
                source_system     TEXT NOT NULL DEFAULT 'sales_online',
                data_category     TEXT,
                period_year       INTEGER,
                period_month      INTEGER,
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
                ADD COLUMN IF NOT EXISTS data_category TEXT,
                ADD COLUMN IF NOT EXISTS period_year INTEGER,
                ADD COLUMN IF NOT EXISTS period_month INTEGER,
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
            CREATE INDEX IF NOT EXISTS idx_file_manifest_source_period
            ON staging.file_manifest (
                source_system,
                data_category,
                period_year,
                period_month,
                transform_status
            )
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


def unique_path(path):
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


def get_env_path(name, default_path):
    return Path(os.getenv(name, default_path))
