"""Crewdible raw API extraction runner."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Engine

from scripts.api.clients.crewdible import CrewdibleClient
from scripts.api.models import EndpointSpec, ManifestRecord
from scripts.api.registry.crewdible import get_endpoint_specs
from scripts.api.storage.manifest import insert_manifest_record
from scripts.api.storage.raw_files import write_raw_response

logger = logging.getLogger(__name__)


def run_crewdible_extract(
    *,
    endpoint_group: str | None = None,
    endpoint_name: str | None = None,
    path_params: dict[str, Any] | None = None,
    request_params: dict[str, Any] | None = None,
    raw_root: str | Path,
    engine: Engine | None = None,
    write_manifest: bool = True,
    compress: bool = False,
    max_pages: int | None = None,
    run_id: str | None = None,
) -> list[ManifestRecord]:
    specs = get_endpoint_specs(endpoint_group=endpoint_group, endpoint_name=endpoint_name)
    if not specs:
        raise RuntimeError("No Crewdible endpoint matched the requested filter.")

    client = CrewdibleClient.from_env()
    client.authenticate()
    run_id = run_id or str(uuid4())

    records: list[ManifestRecord] = []
    for spec in specs:
        logger.info("Fetch Crewdible endpoint: %s", spec.name)
        record = fetch_and_store_endpoint(
            client=client,
            spec=spec,
            path_params=path_params or {},
            request_params=request_params or {},
            raw_root=raw_root,
            compress=compress,
            max_pages=max_pages,
            run_id=run_id,
        )
        records.append(record)
        if write_manifest:
            if engine is None:
                raise RuntimeError("engine is required when write_manifest=True.")
            insert_manifest_record(engine, record)
    return records


def fetch_and_store_endpoint(
    *,
    client: CrewdibleClient,
    spec: EndpointSpec,
    path_params: dict[str, Any],
    request_params: dict[str, Any],
    raw_root: str | Path,
    compress: bool,
    max_pages: int | None,
    run_id: str,
) -> ManifestRecord:
    fetched_at = datetime.now().astimezone()
    endpoint = spec.render_endpoint(path_params)
    payload = build_payload(spec, request_params)
    request_context = {
        "path_params": path_params,
        "payload": payload,
    }
    started = time.monotonic()

    try:
        responses, status_code = fetch_responses(
            client=client,
            spec=spec,
            endpoint=endpoint,
            payload=payload,
            max_pages=max_pages,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        raw_file = write_raw_response(
            raw_root=raw_root,
            spec=spec,
            fetched_at=fetched_at,
            responses=responses,
            compress=compress,
        )
        return ManifestRecord(
            source_system="crewdible",
            endpoint_group=spec.endpoint_group,
            endpoint=endpoint,
            request_method=spec.method,
            request_params=request_context,
            request_hash=hash_request(endpoint, request_context),
            fetched_at=fetched_at,
            fetched_date=fetched_at.date(),
            storage_path=str(raw_file.storage_path),
            file_name=raw_file.file_name,
            file_format=raw_file.file_format,
            is_compressed=raw_file.is_compressed,
            status_code=status_code,
            success=True,
            record_count=raw_file.record_count,
            file_size_bytes=raw_file.file_size_bytes,
            checksum_sha256=raw_file.checksum_sha256,
            duration_ms=duration_ms,
            pagination_key=spec.pagination_strategy,
            run_id=run_id,
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return ManifestRecord(
            source_system="crewdible",
            endpoint_group=spec.endpoint_group,
            endpoint=endpoint,
            request_method=spec.method,
            request_params=request_context,
            request_hash=hash_request(endpoint, request_context),
            fetched_at=fetched_at,
            fetched_date=fetched_at.date(),
            success=False,
            duration_ms=duration_ms,
            pagination_key=spec.pagination_strategy,
            run_id=run_id,
            error_message=str(exc),
        )


def fetch_responses(
    *,
    client: CrewdibleClient,
    spec: EndpointSpec,
    endpoint: str,
    payload: dict[str, Any],
    max_pages: int | None,
) -> tuple[list[dict[str, Any]], int]:
    if spec.pagination_strategy != "page_limit":
        response = client.request(spec.method, endpoint, payload=payload)
        return [response.json()], response.status_code

    responses: list[dict[str, Any]] = []
    page = int(payload.get("page", 1) or 1)
    limit = int(payload.get("limit", 50) or 50)
    status_code = 200

    while True:
        page_payload = {**payload, "page": page, "limit": limit}
        response = client.request(spec.method, endpoint, payload=page_payload)
        status_code = response.status_code
        response_json = response.json()
        responses.append(response_json)

        total_page = extract_total_page(response_json)
        if total_page is None:
            break
        if page >= total_page:
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1

    return responses, status_code


def build_payload(spec: EndpointSpec, request_params: dict[str, Any]) -> dict[str, Any]:
    payload = {**spec.default_payload, **request_params}
    missing = [key for key in spec.required_params if payload.get(key) in (None, "")]
    if missing:
        raise ValueError(f"Missing request params for {spec.name}: {', '.join(missing)}")
    return payload


def extract_total_page(response_json: dict[str, Any]) -> int | None:
    data = response_json.get("data")
    if not isinstance(data, dict):
        return None
    for key in ("total_page", "total_pages", "last_page"):
        value = data.get(key)
        if value not in (None, ""):
            return int(value)
    return None


def hash_request(endpoint: str, request_context: dict[str, Any]) -> str:
    raw = json.dumps({"endpoint": endpoint, **request_context}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()
