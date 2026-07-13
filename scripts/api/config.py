"""Configuration values for API extraction scripts."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from scripts.config import PROJECT_ROOT


class FrozenConfig(BaseModel):
    """Base config model that prevents accidental runtime mutation."""

    model_config = ConfigDict(frozen=True)


class StorageConfig(FrozenConfig):
    """Filesystem locations for raw API responses."""

    crewdible_raw_root: Path = Field(default=PROJECT_ROOT / "data/api/crewdible")
    accurate_raw_root: Path = Field(default=PROJECT_ROOT / "data/api/accurate")


class AccurateConfig(FrozenConfig):
    """Accurate Online API runtime behavior."""

    gateway_url: str = "https://account.accurate.id/api/api-token.do"
    language_profile: str | None = "US"
    timeout_seconds: int = 60
    request_delay_seconds: float = 0.15
    default_page_size: int = 100


class CrewdibleConfig(FrozenConfig):
    """Crewdible API runtime behavior."""

    base_url: str = "https://oms-beta.api.crewdible.com/api/bites"
    timeout_seconds: int = 60


class ApiExtractConfig(FrozenConfig):
    """Runtime configuration for raw API extraction."""

    storage: StorageConfig = Field(default_factory=StorageConfig)
    accurate: AccurateConfig = Field(default_factory=AccurateConfig)
    crewdible: CrewdibleConfig = Field(default_factory=CrewdibleConfig)


def get_api_extract_config() -> ApiExtractConfig:
    return ApiExtractConfig()
