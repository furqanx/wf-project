"""BigSeller raw API extraction runner."""

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

from scripts.api.clients.bigseller import BigSellerClient, is_success_response
from scripts.api.models import EndpointSpec, ManifestRecord
from scripts.api.registry.bigseller import get_endpoint_specs
from scripts.api.storage.manifest import insert_manifest_record
from scripts.api.storage.raw_files import write_raw_response

logger = logging.getLogger(__name__)


def run_bigseller_extract(
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
        raise RuntimeError("No BigSeller endpoint matched the requested filter.")

    client = BigSellerClient.from_env()
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
        logger.info("Fetch BigSeller endpoint: %s", spec.name)
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
    client: BigSellerClient,
    spec: EndpointSpec,
    request_params: dict[str, Any],
    raw_root: str | Path,
    compress: bool,
    max_pages: int | None,
    run_id: str,
) -> ManifestRecord:
    fetched_at = datetime.now().astimezone()
    endpoint = spec.render_endpoint()
    payload = build_payload(spec, request_params)
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
            source_system="bigseller",
            endpoint_group=spec.endpoint_group,
            endpoint=endpoint,
            request_method=spec.method,
            request_params={"payload": payload, "storage_group": spec.storage_folder},
            request_hash=hash_request(endpoint, payload),
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
            source_system="bigseller",
            endpoint_group=spec.endpoint_group,
            endpoint=endpoint,
            request_method=spec.method,
            request_params={"payload": payload, "storage_group": spec.storage_folder},
            request_hash=hash_request(endpoint, payload),
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
    client: BigSellerClient,
    spec: EndpointSpec,
    endpoint: str,
    payload: dict[str, Any],
    max_pages: int | None,
) -> tuple[list[dict[str, Any]], int]:
    if spec.pagination_strategy != "page_limit":
        response = client.request(spec.method, endpoint, payload=payload)
        result = response.json()
        validate_bigseller_response(result)
        return [result], response.status_code

    responses: list[dict[str, Any]] = []
    page = int(payload.get("page", 1) or 1)
    limit = int(payload.get("limit", 50) or 50)
    status_code = 200

    while True:
        page_payload = {**payload, "page": page, "limit": limit}
        response = client.request(spec.method, endpoint, payload=page_payload)
        status_code = response.status_code
        result = response.json()
        validate_bigseller_response(result)
        responses.append(result)

        total_page = extract_total_page(result)
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


def build_effective_request_params(
    *,
    spec: EndpointSpec,
    request_params: dict[str, Any],
    start_date: str | date | None,
    end_date: str | date | None,
) -> dict[str, Any]:
    params = dict(request_params)
    if spec.fetch_mode != "incremental":
        return params
    if start_date is None and end_date is None:
        return params
    if start_date is None or end_date is None:
        raise ValueError("Both start_date and end_date are required for BigSeller incremental fetch.")
    params.setdefault("start_time", format_bigseller_datetime(start_date, end_of_day=False))
    params.setdefault("end_time", format_bigseller_datetime(end_date, end_of_day=True))
    params.setdefault("date_type", 0)
    return params


def format_bigseller_datetime(value: str | date, *, end_of_day: bool) -> str:
    if isinstance(value, date):
        suffix = "23:59:59" if end_of_day else "00:00:00"
        return f"{value.isoformat()} {suffix}"
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt == "%Y-%m-%d":
                parsed = parsed.replace(
                    hour=23 if end_of_day else 0,
                    minute=59 if end_of_day else 0,
                    second=59 if end_of_day else 0,
                )
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError(f"Invalid BigSeller date '{value}'. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.")


def validate_fetch_mode(
    spec: EndpointSpec,
    request_params: dict[str, Any],
    *,
    allow_manual: bool,
) -> None:
    if spec.fetch_mode == "manual" and not allow_manual:
        raise RuntimeError(
            f"Endpoint {spec.name} is marked manual. Re-run with --allow-manual."
        )
    if spec.fetch_mode != "incremental":
        return
    if request_params.get("start_time") and request_params.get("end_time"):
        return
    raise RuntimeError(
        f"Endpoint {spec.name} is incremental and requires start_time/end_time. "
        "Pass --start-date/--end-date or explicit --payload start_time=... --payload end_time=..."
    )


def validate_bigseller_response(result: dict[str, Any]) -> None:
    if is_success_response(result):
        return
    raise RuntimeError(f"BigSeller API returned unsuccessful response: {result}")


def extract_total_page(result: dict[str, Any]) -> int | None:
    data = result.get("data")
    candidates: list[Any] = []
    if isinstance(data, dict):
        candidates.extend(
            [
                data.get("total_page"),
                data.get("total_pages"),
                data.get("page_count"),
                data.get("totalPage"),
                data.get("totalPages"),
                data.get("pageCount"),
            ]
        )
        page_info = data.get("page_info") or data.get("pageInfo")
        if isinstance(page_info, dict):
            candidates.extend(
                [
                    page_info.get("total_page"),
                    page_info.get("total_pages"),
                    page_info.get("page_count"),
                    page_info.get("totalPage"),
                    page_info.get("totalPages"),
                    page_info.get("pageCount"),
                ]
            )
    for candidate in candidates:
        if candidate not in (None, ""):
            return int(candidate)
    return None


def hash_request(endpoint: str, payload: dict[str, Any]) -> str:
    raw = json.dumps({"endpoint": endpoint, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()
