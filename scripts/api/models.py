"""Shared data models for API extraction."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


HttpMethod = Literal["GET", "POST"]
PaginationStrategy = Literal["none", "page_limit"]
FetchMode = Literal["full", "incremental", "manual"]


class ApiBaseModel(BaseModel):
    """Base model config used by API extraction models."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class EndpointSpec(ApiBaseModel):
    """Definition for a raw API endpoint that can be fetched."""

    name: str
    endpoint_group: str
    endpoint: str
    file_prefix: str
    method: HttpMethod = "POST"
    required_params: tuple[str, ...] = Field(default_factory=tuple)
    path_params: tuple[str, ...] = Field(default_factory=tuple)
    pagination_strategy: PaginationStrategy = "none"
    fetch_mode: FetchMode = "full"
    storage_group: str | None = None
    default_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "endpoint_group", "endpoint", "file_prefix")
    @classmethod
    def must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be empty.")
        return value

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("Endpoint must start with '/'.")
        return value

    def render_endpoint(self, params: dict[str, Any] | None = None) -> str:
        """Render path parameters such as /warehouse/{warehouse}."""
        rendered = self.endpoint
        params = params or {}
        for key in self.path_params:
            value = params.get(key)
            if value in (None, ""):
                raise ValueError(f"Missing path parameter '{key}' for endpoint {self.name}.")
            rendered = rendered.replace(f"{{{key}}}", str(value))
        return rendered

    @property
    def storage_folder(self) -> str:
        return self.storage_group or self.endpoint_group


class RawFileInfo(ApiBaseModel):
    """Metadata for a raw response file written to disk."""

    storage_path: Path
    file_name: str
    file_format: str
    is_compressed: bool
    file_size_bytes: int
    checksum_sha256: str
    record_count: int


class ManifestRecord(ApiBaseModel):
    """Metadata row for api_staging.raw_file_manifest."""

    source_system: str
    endpoint_group: str
    endpoint: str
    request_method: str
    request_params: dict[str, Any]
    request_hash: str
    fetched_at: datetime
    fetched_date: date
    success: bool
    storage_path: str | None = None
    file_name: str | None = None
    file_format: str | None = None
    is_compressed: bool = False
    status_code: int | None = None
    record_count: int | None = None
    file_size_bytes: int | None = None
    checksum_sha256: str | None = None
    duration_ms: int | None = None
    page_number: int | None = None
    pagination_key: str | None = None
    run_id: str | None = None
    error_message: str | None = None
