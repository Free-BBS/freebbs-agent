from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from typing import Any

from .config import AgentConfig
from .server_settings import (
    SETTINGS_UNAVAILABLE_MESSAGE,
    ServerSettingsError,
    ServerSettingsProvider,
    ServerSettingsSnapshot,
)


class AIClientError(RuntimeError):
    pass


class ChatClient:
    def __init__(
        self,
        config: AgentConfig,
        *,
        settings_provider: ServerSettingsProvider | None = None,
        client_factory=None,
    ):
        self._config = config
        if config.server_settings_partially_configured:
            raise AIClientError(SETTINGS_UNAVAILABLE_MESSAGE)
        if settings_provider is None and config.server_settings_enabled:
            settings_provider = ServerSettingsProvider(
                config.settings_socket_path or "",
                config.agent_service_token or "",
                timeout_seconds=config.settings_timeout_seconds,
                cache_ttl_seconds=config.settings_cache_ttl_seconds,
                stale_ttl_seconds=config.settings_stale_ttl_seconds,
            )
        self._settings_provider = settings_provider
        self._client_factory = client_factory or self._create_openai_client
        self._client = None
        self._client_fingerprint: str | None = None
        self._client_lock = threading.Lock()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        snapshot = self._get_settings_snapshot()
        client = self._get_client(snapshot)
        payload = self._build_payload(
            messages,
            snapshot,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        try:
            response = client.chat.completions.create(**payload)
        except Exception:  # pragma: no cover - SDK/provider specific
            raise AIClientError("AI provider request failed") from None

        choice = response.choices[0]
        return {
            "answer": choice.message.content,
            "model": getattr(response, "model", payload["model"]),
            "finish_reason": getattr(choice, "finish_reason", None),
        }

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        snapshot = self._get_settings_snapshot()
        client = self._get_client(snapshot)
        payload = self._build_payload(
            messages,
            snapshot,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        payload["stream"] = True

        try:
            stream = client.chat.completions.create(**payload)
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                delta = getattr(chunk.choices[0], "delta", None)
                content = getattr(delta, "content", None)
                if content:
                    yield content
        except Exception:  # pragma: no cover - SDK/provider specific
            raise AIClientError("AI provider request failed") from None

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        snapshot: ServerSettingsSnapshot,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or snapshot.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _get_settings_snapshot(self) -> ServerSettingsSnapshot:
        if self._settings_provider is not None:
            try:
                return self._settings_provider.get_snapshot()
            except ServerSettingsError:
                raise AIClientError(SETTINGS_UNAVAILABLE_MESSAGE) from None

        if not self._config.api_key:
            raise AIClientError("missing AGENT_API_KEY or OPENAI_API_KEY")

        return ServerSettingsSnapshot(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            model=self._config.model,
            course_materials_root=self._config.course_materials_root,
            revision="static-environment",
        )

    def _get_client(self, snapshot: ServerSettingsSnapshot):
        fingerprint = self._settings_fingerprint(snapshot)

        with self._client_lock:
            if self._client is not None and self._client_fingerprint == fingerprint:
                return self._client

            try:
                client = self._client_factory(
                    api_key=snapshot.api_key,
                    base_url=snapshot.base_url,
                    timeout=self._config.request_timeout_seconds,
                )
            except AIClientError:
                raise
            except Exception:
                raise AIClientError("failed to initialize AI provider client") from None

            self._client = client
            self._client_fingerprint = fingerprint
            return client

    def course_materials_root(self) -> str:
        return self._get_settings_snapshot().course_materials_root

    @staticmethod
    def _settings_fingerprint(snapshot: ServerSettingsSnapshot) -> str:
        digest = hashlib.sha256()
        for value in (
            snapshot.revision,
            snapshot.base_url,
            snapshot.model,
            snapshot.api_key,
        ):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    @staticmethod
    def _create_openai_client(**kwargs):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency check covers this
            raise AIClientError("openai package is not installed") from exc

        return OpenAI(**kwargs)
