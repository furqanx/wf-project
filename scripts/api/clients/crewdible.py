"""Crewdible API client."""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any

import requests

from scripts.api.config import get_api_extract_config
from scripts.utils.env import get_env, load_dotenv_file


DEFAULT_BASE_URL = "https://oms-beta.api.crewdible.com/api/bites"
MD5_PATTERN = re.compile(r"^[a-fA-F0-9]{32}$")


class CrewdibleClient:
    """Small client for Crewdible OAuth, seller login, and API requests."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        email: str,
        password: str,
        timeout_seconds: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.email = email
        self.password = password
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.token_api: str | None = None
        self.token_login: str | None = None

    @classmethod
    def from_env(cls) -> "CrewdibleClient":
        load_dotenv_file()
        config = get_api_extract_config()
        return cls(
            base_url=get_env("CREWDIBLE_BASE_URL", config.crewdible.base_url) or config.crewdible.base_url,
            client_id=get_env("CREWDIBLE_CLIENT_ID", required=True) or "",
            client_secret=get_env("CREWDIBLE_CLIENT_SECRET", required=True) or "",
            email=get_env("CREWDIBLE_EMAIL", required=True) or "",
            password=get_env("CREWDIBLE_PASSWORD", required=True) or "",
            timeout_seconds=config.crewdible.timeout_seconds,
        )

    def request_oauth_token(self) -> str:
        auth_value = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        response = self.session.post(
            f"{self.base_url}/oauth/token",
            headers={
                "Authorization": f"Basic {auth_value}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("Crewdible OAuth response does not contain access_token.")
        self.token_api = token
        return token

    def login_seller(self) -> str:
        api_token = self.token_api or self.request_oauth_token()
        response = self.session.post(
            f"{self.base_url}/users/login",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            json={"email": self.email, "password": self._password_md5()},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        token = response.json().get("data", {}).get("token")
        if not token:
            raise RuntimeError("Crewdible login response does not contain data.token.")
        self.token_login = token
        return token

    def authenticate(self) -> None:
        self.request_oauth_token()
        self.login_seller()

    def auth_headers(self) -> dict[str, str]:
        if not self.token_api or not self.token_login:
            self.authenticate()
        return {
            "Authorization": f"Bearer {self.token_api}",
            "X-CREW-TOKEN": self.token_login or "",
            "Content-Type": "application/json",
        }

    def post(self, endpoint: str, payload: dict[str, Any] | None = None) -> requests.Response:
        return self.request("POST", endpoint, payload=payload)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        response = self.session.request(
            method.upper(),
            url,
            headers=self.auth_headers(),
            json=payload or {},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response

    def _password_md5(self) -> str:
        if MD5_PATTERN.match(self.password):
            return self.password.lower()
        return hashlib.md5(self.password.encode()).hexdigest()
