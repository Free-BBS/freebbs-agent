from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx


DEFAULT_SETTINGS_ENDPOINT = "/internal/v1/agent-config"
SETTINGS_UNAVAILABLE_MESSAGE = "server-managed model configuration is unavailable"
_CONFIG_MISSING_CODES = {
    "agent_config_missing",
    "agent_configuration_missing",
    "agent_settings_missing",
    "configuration_missing",
    "model_configuration_missing",
}


@dataclass(frozen=True)
class ServerSettingsSnapshot:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    course_materials_root: str
    revision: str


class ServerSettingsError(RuntimeError):
    """A deliberately sanitized server-settings failure."""

    def __init__(self, *, invalidate_cache: bool = False):
        super().__init__(SETTINGS_UNAVAILABLE_MESSAGE)
        self.invalidate_cache = invalidate_cache


class ServerSettingsProvider:
    """Fetch and cache model settings from FREE-BBS over a Unix socket."""

    def __init__(
        self,
        socket_path: str,
        service_token: str,
        *,
        endpoint_path: str = DEFAULT_SETTINGS_ENDPOINT,
        timeout_seconds: float = 2.0,
        cache_ttl_seconds: float = 30.0,
        stale_ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        client_factory: Callable[[], httpx.Client] | None = None,
    ):
        if not socket_path or not os.path.isabs(socket_path):
            raise ValueError("server settings socket path must be absolute")
        if not service_token:
            raise ValueError("server settings service token is required")
        if not endpoint_path.startswith("/"):
            raise ValueError("server settings endpoint path must start with /")
        if timeout_seconds <= 0:
            raise ValueError("server settings timeout must be positive")
        if cache_ttl_seconds < 0:
            raise ValueError("server settings cache TTL must not be negative")
        if stale_ttl_seconds < cache_ttl_seconds:
            raise ValueError("server settings stale TTL must be at least the cache TTL")

        self._socket_path = socket_path
        self._service_token = service_token
        self._endpoint_path = endpoint_path
        self._timeout_seconds = timeout_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._stale_ttl_seconds = stale_ttl_seconds
        self._clock = clock
        self._client_factory = client_factory or self._new_http_client
        self._lock = threading.Lock()
        self._cached_snapshot: ServerSettingsSnapshot | None = None
        self._cached_at: float | None = None

    def get_snapshot(self) -> ServerSettingsSnapshot:
        now = self._clock()
        with self._lock:
            if self._is_fresh(now):
                return self._cached_snapshot  # type: ignore[return-value]

            try:
                snapshot = self._fetch_snapshot()
            except ServerSettingsError as exc:
                failure_time = self._clock()
                if exc.invalidate_cache:
                    self._clear_cache()
                elif self._can_use_stale(failure_time):
                    return self._cached_snapshot  # type: ignore[return-value]
                else:
                    self._clear_cache()
                raise ServerSettingsError(invalidate_cache=exc.invalidate_cache) from None

            self._cached_snapshot = snapshot
            self._cached_at = self._clock()
            return snapshot

    def clear_cache(self) -> None:
        with self._lock:
            self._clear_cache()

    def _is_fresh(self, now: float) -> bool:
        return (
            self._cached_snapshot is not None
            and self._cached_at is not None
            and now - self._cached_at < self._cache_ttl_seconds
        )

    def _can_use_stale(self, now: float) -> bool:
        return (
            self._cached_snapshot is not None
            and self._cached_at is not None
            and now - self._cached_at <= self._stale_ttl_seconds
        )

    def _clear_cache(self) -> None:
        self._cached_snapshot = None
        self._cached_at = None

    def _new_http_client(self) -> httpx.Client:
        return httpx.Client(
            base_url="http://localhost",
            transport=httpx.HTTPTransport(uds=self._socket_path),
            timeout=httpx.Timeout(self._timeout_seconds),
            trust_env=False,
        )

    def _fetch_snapshot(self) -> ServerSettingsSnapshot:
        try:
            with self._client_factory() as client:
                response = client.get(
                    self._endpoint_path,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self._service_token}",
                    },
                )
        except (httpx.TimeoutException, httpx.TransportError):
            raise ServerSettingsError() from None
        except Exception:
            raise ServerSettingsError() from None

        if response.status_code in {401, 403, 404}:
            raise ServerSettingsError(invalidate_cache=True)

        payload = _response_json(response)
        if _payload_reports_missing_configuration(payload):
            raise ServerSettingsError(invalidate_cache=True)

        if response.status_code >= 500:
            raise ServerSettingsError()
        if response.status_code != 200:
            raise ServerSettingsError(invalidate_cache=True)

        try:
            return _snapshot_from_payload(payload)
        except (TypeError, ValueError):
            raise ServerSettingsError(invalidate_cache=True) from None


def _response_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _payload_reports_missing_configuration(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False

    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
    else:
        code = payload.get("code")

    return isinstance(code, str) and code.strip().lower() in _CONFIG_MISSING_CODES


def _snapshot_from_payload(payload: dict[str, Any] | None) -> ServerSettingsSnapshot:
    if payload is None:
        raise ValueError("settings payload must be an object")

    api_key = _required_string(payload, "apiKey")
    base_url = _required_string(payload, "baseUrl")
    model = _required_string(payload, "model")
    course_materials_root = _optional_string(payload, "courseMaterialsRoot")
    revision_value = payload.get("revision")

    parsed_base_url = urlparse(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise ValueError("settings base URL must be absolute HTTP(S)")
    if course_materials_root and not os.path.isabs(course_materials_root):
        raise ValueError("course materials root must be absolute")
    if isinstance(revision_value, bool) or not isinstance(revision_value, (str, int)):
        raise ValueError("settings revision must be a string or integer")

    revision = str(revision_value).strip()
    if not revision:
        raise ValueError("settings revision is required")

    return ServerSettingsSnapshot(
        api_key=api_key,
        base_url=base_url,
        model=model,
        course_materials_root=course_materials_root,
        revision=revision,
    )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()
