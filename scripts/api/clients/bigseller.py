"""BigSeller Open API client."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import requests

from scripts.api.config import get_api_extract_config
from scripts.utils.env import get_env, load_dotenv_file


TOKEN_EXPIRED_ERROR_CODE = "40101005"


class BigSellerClient:
    """Client for signed BigSeller Open API requests."""

    def __init__(
        self,
        *,
        app_id: str,
        app_key: str,
        access_token: str,
        refresh_token: str | None,
        base_url: str,
        timeout_seconds: int = 60,
    ) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    @classmethod
    def from_env(cls) -> "BigSellerClient":
        load_dotenv_file()
        config = get_api_extract_config()
        return cls(
            app_id=get_env("BIGSELLER_APP_ID", required=True) or "",
            app_key=get_env("BIGSELLER_APP_KEY", required=True) or "",
            access_token=get_env("BIGSELLER_ACCESS_TOKEN", required=True) or "",
            refresh_token=get_env("BIGSELLER_REFRESH_TOKEN"),
            base_url=get_env("BIGSELLER_BASE_URL", config.bigseller.base_url) or config.bigseller.base_url,
            timeout_seconds=config.bigseller.timeout_seconds,
        )

    def post(self, endpoint: str, payload: dict[str, Any] | None = None) -> requests.Response:
        return self.request("POST", endpoint, payload=payload)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
        retry_on_expired_token: bool = True,
    ) -> requests.Response:
        endpoint = normalize_endpoint(endpoint)
        payload = payload or {}
        response = self.session.request(
            method.upper(),
            f"{self.base_url}{endpoint}",
            headers=self.build_headers(endpoint, payload),
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        if retry_on_expired_token and self._is_token_expired(response):
            self.refresh_access_token()
            response = self.session.request(
                method.upper(),
                f"{self.base_url}{endpoint}",
                headers=self.build_headers(endpoint, payload),
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()

        return response

    def build_headers(self, endpoint: str, payload: dict[str, Any]) -> dict[str, str]:
        return {
            "x-bs-app-id": self.app_id,
            "x-bs-access-token": self.access_token,
            "x-bs-sign": self.generate_signature(endpoint, payload),
            "Content-Type": "application/json",
        }

    def generate_signature(self, endpoint: str, params: dict[str, Any]) -> str:
        """Generate x-bs-sign following BigSeller HMAC-SHA256 rules."""
        filtered_params = {
            key: value
            for key, value in params.items()
            if key and key != "sign" and value not in (None, "")
        }
        query_parts: list[str] = []
        for key in sorted(filtered_params):
            value = filtered_params[key]
            if isinstance(value, (dict, list)):
                value_text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            else:
                value_text = str(value)
            query_parts.append(f"{key}={value_text}")

        query_string = "&".join(query_parts)
        string_to_sign = f"{self.app_id}{normalize_endpoint(endpoint)}/"
        if query_string:
            string_to_sign += query_string

        digest = hmac.new(
            self.app_key.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest.lower()

    def refresh_access_token(self) -> dict[str, Any]:
        if not self.refresh_token:
            raise RuntimeError("BIGSELLER_REFRESH_TOKEN is required to refresh access token.")

        endpoint = "/api/auth/v1/refresh_access_token"
        payload = {"refresh_token": self.refresh_token}
        response = self.session.post(
            f"{self.base_url}{endpoint}",
            headers=self.build_headers(endpoint, payload),
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()
        if not is_success_response(result):
            raise RuntimeError(f"BigSeller refresh token failed: {result}")

        data = result.get("data", {})
        new_access_token = data.get("access_token")
        if not new_access_token:
            raise RuntimeError("BigSeller refresh response does not contain data.access_token.")
        self.access_token = new_access_token
        self.refresh_token = data.get("refresh_token") or self.refresh_token
        return data

    def _is_token_expired(self, response: requests.Response) -> bool:
        try:
            result = response.json()
        except ValueError:
            return False
        return str(result.get("error_code")) == TOKEN_EXPIRED_ERROR_CODE


def normalize_endpoint(endpoint: str) -> str:
    return endpoint if endpoint.startswith("/") else f"/{endpoint}"


def is_success_response(result: dict[str, Any]) -> bool:
    success = result.get("success")
    if isinstance(success, bool):
        return success
    if isinstance(success, str):
        return success.upper() == "TRUE"
    if result.get("code") == 200:
        return True
    return False
