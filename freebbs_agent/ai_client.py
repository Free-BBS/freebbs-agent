from __future__ import annotations

import base64
import hashlib
import re
import threading
from collections.abc import Iterator
from typing import Any

from .config import AgentConfig
from .model_options import reasoning_options, with_images
from .reasoning_stream import current_progress, ProgressCancelled
from .server_settings import (
    SETTINGS_UNAVAILABLE_MESSAGE,
    ServerSettingsError,
    ServerSettingsProvider,
    ServerSettingsSnapshot,
)


class AIClientError(RuntimeError):
    def __init__(self, message: str, *, code: str = "ai_provider_error"):
        super().__init__(message)
        self.code = code


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
        self._image_client = None
        self._image_client_fingerprint: str | None = None
        self._client_lock = threading.Lock()
        self._image_model_by_fingerprint: dict[str, str] = {}

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        vision_images: list | None = None,
    ) -> dict[str, Any]:
        snapshot = self._get_settings_snapshot()
        client = self._get_client(snapshot)
        payload = self._build_payload(
            messages,
            snapshot,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            vision_images=vision_images,
        )

        progress = current_progress.get()
        if progress is not None:
            return self._chat_with_progress(client, payload, progress)

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

    def _chat_with_progress(self, client, payload, progress):
        parts = []
        model = payload["model"]
        finish_reason = None
        try:
            if progress.cancelled.is_set():
                raise ProgressCancelled()
            stream = client.chat.completions.create(**payload, stream=True)
            with progress.track(stream) as call_id:
                for chunk in stream:
                    if not getattr(chunk, "choices", None):
                        continue
                    choice = chunk.choices[0]
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None)
                    reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                    progress.send(call_id, reasoning=reasoning, content=content)
                    if isinstance(content, str):
                        parts.append(content)
                    model = getattr(chunk, "model", None) or model
                    finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            if finish_reason is None:
                raise AIClientError("AI provider stream ended before completion")
            return {"answer": "".join(parts), "model": model, "finish_reason": finish_reason}
        except ProgressCancelled:
            raise
        except Exception:
            raise AIClientError("AI provider request failed") from None

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        vision_images: list | None = None,
    ) -> Iterator[str]:
        snapshot = self._get_settings_snapshot()
        client = self._get_client(snapshot)
        payload = self._build_payload(
            messages,
            snapshot,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            vision_images=vision_images,
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

    def generate_image(self, prompt: str, *, size: str = "2048x2048") -> dict[str, str]:
        snapshot = self._get_settings_snapshot()
        client = self._get_client(snapshot)
        image_client = self._get_image_client(snapshot, client)
        fingerprint = self._settings_fingerprint(snapshot)
        model = self._config.image_generation_model or self._image_model_by_fingerprint.get(
            fingerprint
        )
        try:
            if not model:
                candidates = [
                    str(item.id)
                    for item in client.models.list().data
                    if "seedream" in str(getattr(item, "id", "")).casefold()
                ]
                if not candidates:
                    raise AIClientError(
                        "No image generation model is available",
                        code="image_model_unavailable",
                    )

                def version_key(value: str):
                    return tuple(int(part) for part in re.findall(r"\d+", value))

                model = max(candidates, key=version_key)
                self._image_model_by_fingerprint[fingerprint] = model

            response = image_client.images.generate(
                model=model,
                prompt=prompt,
                size=size,
                response_format="b64_json",
                extra_body={"watermark": True},
                timeout=self._config.image_generation_timeout_seconds,
            )
            item = response.data[0]
            encoded = getattr(item, "b64_json", None)
            if not isinstance(encoded, str) or not encoded:
                raise AIClientError(
                    "Image provider returned no image data",
                    code="image_data_missing",
                )
            raw = base64.b64decode(encoded, validate=True)
            if not raw or len(raw) > 20 * 1024 * 1024:
                raise AIClientError(
                    "Image provider returned invalid image data",
                    code="image_data_invalid",
                )
            mime = "image/png"
            if raw.startswith(b"\xff\xd8\xff"):
                mime = "image/jpeg"
            elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
                mime = "image/webp"
            return {
                "data_url": f"data:{mime};base64,{encoded}",
                "model": model,
            }
        except AIClientError:
            raise
        except Exception as exc:  # pragma: no cover - SDK/provider specific
            status = getattr(exc, "status_code", None)
            code = (
                f"image_provider_http_{status}"
                if isinstance(status, int)
                else "image_provider_error"
            )
            raise AIClientError("Image generation provider request failed", code=code) from None

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        snapshot: ServerSettingsSnapshot,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        vision_images: list | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or snapshot.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(reasoning_options(payload["model"], reasoning_effort))
        payload["messages"] = with_images(messages, vision_images, payload["model"])
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

    def _get_image_client(self, snapshot: ServerSettingsSnapshot, default_client):
        base_url = self._config.image_generation_base_url
        if not base_url or base_url.rstrip("/") == snapshot.base_url.rstrip("/"):
            return default_client

        fingerprint = f"{self._settings_fingerprint(snapshot)}:{base_url.rstrip('/')}"
        with self._client_lock:
            if (
                self._image_client is not None
                and self._image_client_fingerprint == fingerprint
            ):
                return self._image_client
            try:
                client = self._client_factory(
                    api_key=snapshot.api_key,
                    base_url=base_url,
                    timeout=self._config.image_generation_timeout_seconds,
                )
            except AIClientError:
                raise
            except Exception:
                raise AIClientError(
                    "failed to initialize image provider client",
                    code="image_provider_initialization_failed",
                ) from None
            self._image_client = client
            self._image_client_fingerprint = fingerprint
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
