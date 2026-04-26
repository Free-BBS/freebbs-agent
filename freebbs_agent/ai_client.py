from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .config import AgentConfig


class AIClientError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, config: AgentConfig):
        self._config = config
        self._client = None

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        client = self._get_client()
        payload = self._build_payload(messages, model=model, temperature=temperature, max_tokens=max_tokens)

        try:
            response = client.chat.completions.create(**payload)
        except Exception as exc:  # pragma: no cover - SDK/provider specific
            raise AIClientError(str(exc)) from exc

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
        client = self._get_client()
        payload = self._build_payload(messages, model=model, temperature=temperature, max_tokens=max_tokens)
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
        except Exception as exc:  # pragma: no cover - SDK/provider specific
            raise AIClientError(str(exc)) from exc

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not self._config.api_key:
            raise AIClientError("missing AGENT_API_KEY or OPENAI_API_KEY")

        payload: dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency check covers this
            raise AIClientError("openai package is not installed") from exc

        self._client = OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=self._config.request_timeout_seconds,
        )
        return self._client
