"""Accurate Online API client."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

from scripts.api.config import get_api_extract_config
from scripts.utils.env import get_env, load_dotenv_file


class AccurateClient:
    """Client for Accurate API Token authentication and signed API requests."""

    def __init__(
        self,
        *,
        api_token: str,
        signature_secret: str,
        gateway_url: str,
        host: str | None = None,
        language_profile: str | None,
        timeout_seconds: int = 60,
        min_request_interval_seconds: float = 0.15,
    ) -> None:
        self.api_token = api_token
        self.signature_secret = signature_secret
        self.gateway_url = gateway_url
        self.host = host.rstrip("/") if host else None
        self.language_profile = language_profile
        self.timeout_seconds = timeout_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self._last_request_at: float | None = None
        self.session = requests.Session()

    @classmethod
    def from_env(cls) -> "AccurateClient":
        load_dotenv_file()
        config = get_api_extract_config()
        return cls(
            api_token=get_env("ACCURATE_API_TOKEN", required=True) or "",
            signature_secret=get_env("ACCURATE_SIGNATURE_SECRET", required=True) or "",
            gateway_url=config.accurate.gateway_url,
            host=get_env("ACCURATE_HOST"),
            language_profile=config.accurate.language_profile,
            timeout_seconds=config.accurate.timeout_seconds,
            min_request_interval_seconds=config.accurate.request_delay_seconds,
        )

    def get_api_token_info(self) -> dict[str, Any]:
        response = self.session.post(
            self.gateway_url,
            headers=self.auth_headers(),
            timeout=self.timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("s"):
            raise RuntimeError(f"Accurate api-token.do failed: {result}")

        host = extract_host_from_token_info(result)
        if not host:
            raise RuntimeError("Accurate api-token.do response does not contain host.")
        self.host = host.rstrip("/")
        return result

    def get_host(self) -> str:
        if not self.host:
            self.get_api_token_info()
        if not self.host:
            raise RuntimeError("Accurate host is not available.")
        return self.host

    def get_list(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self.request("GET", endpoint, action="list", params=params)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        action: str | None = None,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        url = self.build_url(endpoint, action=action)
        self._respect_rate_limit()
        response = self.session.request(
            method.upper(),
            url,
            headers=self.auth_headers(),
            params=params,
            json=payload,
            timeout=self.timeout_seconds,
            allow_redirects=True,
        )
        self._update_host_from_redirect(response)
        response.raise_for_status()
        return response

    def _respect_rate_limit(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            wait_seconds = self.min_request_interval_seconds - elapsed
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        self._last_request_at = time.monotonic()

    def build_url(self, endpoint: str, *, action: str | None = None) -> str:
        normalized_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        if normalized_endpoint.endswith(".do"):
            api_path = normalized_endpoint
        elif action:
            api_path = f"{normalized_endpoint}/{action}.do"
        else:
            api_path = f"{normalized_endpoint}.do"
        return f"{self.get_host()}/accurate{api_path}"

    def auth_headers(self) -> dict[str, str]:
        timestamp = self._generate_timestamp()
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "X-Api-Timestamp": timestamp,
            "X-Api-Signature": self._generate_signature(timestamp),
        }
        if self.language_profile:
            headers["X-Language-Profile"] = self.language_profile
        return headers

    def _generate_timestamp(self) -> str:
        return datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    def _generate_signature(self, timestamp: str) -> str:
        digest = hmac.new(
            self.signature_secret.encode("utf-8"),
            timestamp.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _update_host_from_redirect(self, response: requests.Response) -> None:
        if not response.history:
            return
        parsed = urlparse(response.url)
        if parsed.scheme and parsed.netloc:
            self.host = f"{parsed.scheme}://{parsed.netloc}"


def extract_host_from_token_info(result: dict[str, Any]) -> str | None:
    data = result.get("d", {})
    candidates = (
        data.get("database", {}),
        data.get("data usaha", {}),
        data.get("dataUsaha", {}),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("host"):
            return str(candidate["host"])
    return None
