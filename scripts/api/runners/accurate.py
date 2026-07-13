"""Accurate raw API extraction runner."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Engine

from scripts.api.clients.accurate import AccurateClient
from scripts.api.models import EndpointSpec, ManifestRecord
from scripts.api.registry.accurate import get_endpoint_specs
from scripts.api.storage.manifest import insert_manifest_record
from scripts.api.storage.raw_files import write_raw_response

logger = logging.getLogger(__name__)


def run_accurate_extract(
    *,
    endpoint_group: str | None = None,
    endpoint_name: str | None = None,
    storage_group_prefix: str | None = None,
    request_params: dict[str, Any] | None = None,
    fetch_mode: str | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    raw_root: str | Path,
    engine: Engine | None = None,
    write_manifest: bool = True,
    compress: bool = False,
    max_pages: int | None = None,
    allow_manual: bool = False,
    run_id: str | None = None,
) -> list[ManifestRecord]:
    specs = get_endpoint_specs(
        endpoint_group=endpoint_group,
        endpoint_name=endpoint_name,
        storage_group_prefix=storage_group_prefix,
        fetch_mode=fetch_mode,
    )
    if not specs:
        raise RuntimeError("No Accurate endpoint matched the requested filter.")

    client = AccurateClient.from_env()
    client.get_host()
    run_id = run_id or str(uuid4())

    records: list[ManifestRecord] = []
    for spec in specs:
        effective_request_params = build_effective_request_params(
            spec=spec,
            request_params=request_params or {},
            start_date=start_date,
            end_date=end_date,
        )
        validate_fetch_mode(spec, effective_request_params, allow_manual=allow_manual)
        logger.info("Fetch Accurate endpoint: %s", spec.name)
        record = fetch_and_store_endpoint(
            client=client,
            spec=spec,
            request_params=effective_request_params,
            raw_root=raw_root,
            compress=compress,
            max_pages=max_pages,
            run_id=run_id,
        )
        records.append(record)
        if write_manifest:
            if engine is None:
                raise RuntimeError("engine is required when write_manifest=True.")
            manifest_id = insert_manifest_record(engine, record)
            records[-1] = record.model_copy(update={"manifest_id": manifest_id})
    return records


def fetch_and_store_endpoint(
    *,
    client: AccurateClient,
    spec: EndpointSpec,
    request_params: dict[str, Any],
    raw_root: str | Path,
    compress: bool,
    max_pages: int | None,
    run_id: str,
) -> ManifestRecord:
    fetched_at = datetime.now().astimezone()
    endpoint = spec.render_endpoint()
    params = build_params(spec, request_params)
    started = time.monotonic()

    try:
        responses, status_code = fetch_responses(
            client=client,
            spec=spec,
            endpoint=endpoint,
            params=params,
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
            source_system="accurate",
            endpoint_group=spec.endpoint_group,
            endpoint=endpoint,
            request_method=spec.method,
            request_params={"params": params, "storage_group": spec.storage_folder},
            request_hash=hash_request(endpoint, params),
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
            source_system="accurate",
            endpoint_group=spec.endpoint_group,
            endpoint=endpoint,
            request_method=spec.method,
            request_params={"params": params, "storage_group": spec.storage_folder},
            request_hash=hash_request(endpoint, params),
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
    client: AccurateClient,
    spec: EndpointSpec,
    endpoint: str,
    params: dict[str, Any],
    max_pages: int | None,
) -> tuple[list[dict[str, Any]], int]:
    responses: list[dict[str, Any]] = []
    page = int(params.get("sp.page", 1) or 1)
    status_code = 200

    while True:
        page_params = {**params, "sp.page": page}
        response = client.get_list(endpoint, params=page_params)
        status_code = response.status_code
        response_json = response.json()
        responses.append(response_json)

        if not response_json.get("s"):
            raise RuntimeError(f"Accurate API returned unsuccessful response: {response_json}")

        page_count = extract_page_count(response_json)
        if page >= page_count:
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1

    return responses, status_code


def build_params(spec: EndpointSpec, request_params: dict[str, Any]) -> dict[str, Any]:
    params = {**spec.default_payload, **request_params}
    missing = [key for key in spec.required_params if params.get(key) in (None, "")]
    if missing:
        raise ValueError(f"Missing request params for {spec.name}: {', '.join(missing)}")
    return params


def build_effective_request_params(
    *,
    spec: EndpointSpec,
    request_params: dict[str, Any],
    start_date: str | date | None,
    end_date: str | date | None,
) -> dict[str, Any]:
    """Add an Accurate date filter for incremental endpoints when requested."""
    params = dict(request_params)
    if spec.fetch_mode != "incremental" or has_incremental_filter(params):
        return params
    if start_date is None and end_date is None:
        return params
    if start_date is None or end_date is None:
        raise ValueError("Both start_date and end_date are required for incremental date filtering.")
    if not spec.date_filter_field:
        raise ValueError(f"Endpoint {spec.name} has no date_filter_field configured.")

    field = spec.date_filter_field
    params[f"filter.{field}.op"] = "BETWEEN"
    params[f"filter.{field}.val[0]"] = format_accurate_date(start_date)
    params[f"filter.{field}.val[1]"] = format_accurate_date(end_date)
    return params


def format_accurate_date(value: str | date) -> str:
    """Return Accurate-friendly dd/mm/YYYY date text."""
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or DD/MM/YYYY.")


def validate_fetch_mode(
    spec: EndpointSpec,
    request_params: dict[str, Any],
    *,
    allow_manual: bool,
) -> None:
    if spec.fetch_mode == "manual" and not allow_manual:
        raise RuntimeError(
            f"Endpoint {spec.name} is marked manual. Re-run with an explicit manual override."
        )
    if spec.fetch_mode != "incremental":
        return

    if has_incremental_filter(request_params):
        return
    raise RuntimeError(
        f"Endpoint {spec.name} is marked incremental and requires a date/modified filter. "
        "Pass filter params with --payload, for example --payload filter.transDate.op=BETWEEN ..."
    )


def has_incremental_filter(params: dict[str, Any]) -> bool:
    incremental_keywords = ("filter.trans", "filter.modified", "filter.created", "filter.date")
    return any(key.startswith(incremental_keywords) for key in params)


def extract_page_count(response_json: dict[str, Any]) -> int:
    sp = response_json.get("sp")
    if isinstance(sp, dict) and sp.get("pageCount") not in (None, ""):
        return int(sp["pageCount"])
    return 1


def hash_request(endpoint: str, params: dict[str, Any]) -> str:
    raw = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()
