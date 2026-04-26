from __future__ import annotations

import json

from flask import Flask, Response, jsonify, request, stream_with_context

from .ai_client import AIClientError, ChatClient
from .config import AgentConfig
from .security import add_local_cors_headers, is_loopback_addr, reject_non_loopback_requests


def create_app(config: AgentConfig | None = None, chat_client: ChatClient | None = None) -> Flask:
    app_config = config or AgentConfig.from_env()
    app = Flask(__name__)
    app.config["AGENT_CONFIG"] = app_config
    app.chat_client = chat_client or ChatClient(app_config)  # type: ignore[attr-defined]

    app.before_request(reject_non_loopback_requests)
    app.after_request(add_local_cors_headers)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "freebbs-agent"})

    @app.post("/api/v1/chat")
    def chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return validation_error("request body must be a JSON object")

        try:
            messages = normalize_messages(payload, app_config.system_prompt)
            temperature = optional_float(payload, "temperature")
            max_tokens = optional_int(payload, "max_tokens")
            stream = optional_bool(payload, "stream")
        except ValueError as exc:
            return validation_error(str(exc))

        model = payload.get("model")
        if model is not None and not isinstance(model, str):
            return validation_error("model must be a string")

        if stream:
            return Response(
                stream_with_context(
                    sse_chat_stream(
                        app.chat_client,  # type: ignore[attr-defined]
                        messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                ),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        try:
            result = app.chat_client.chat(  # type: ignore[attr-defined]
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except AIClientError as exc:
            return jsonify({"error": {"code": "ai_provider_error", "message": str(exc)}}), 502

        return jsonify(result)

    return app


def normalize_messages(payload: dict, default_system_prompt: str | None = None) -> list[dict[str, str]]:
    messages = payload.get("messages")
    if messages is not None:
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty array")

        normalized = []
        has_system_prompt = False
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError("each message must be an object")
            role = message.get("role")
            content = message.get("content")
            if role not in {"system", "user", "assistant"}:
                raise ValueError("message role must be system, user, or assistant")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("message content must be a non-empty string")
            has_system_prompt = has_system_prompt or role == "system"
            normalized.append({"role": role, "content": content})

        if default_system_prompt and not has_system_prompt:
            normalized.insert(0, {"role": "system", "content": default_system_prompt})
        return normalized

    user_message = payload.get("message")
    if not isinstance(user_message, str) or not user_message.strip():
        raise ValueError("message must be a non-empty string")

    normalized = []
    system_prompt = payload.get("system")
    if system_prompt is not None:
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system must be a non-empty string")
        normalized.append({"role": "system", "content": system_prompt})
    elif default_system_prompt:
        normalized.append({"role": "system", "content": default_system_prompt})

    normalized.append({"role": "user", "content": user_message})
    return normalized


def optional_float(payload: dict, key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(value)


def optional_int(payload: dict, key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def optional_bool(payload: dict, key: str) -> bool:
    value = payload.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def sse_chat_stream(chat_client, messages, *, model=None, temperature=None, max_tokens=None):
    try:
        for chunk in chat_client.stream_chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            for char in chunk:
                yield sse_event({"delta": char})
        yield sse_event({"done": True})
    except AIClientError as exc:
        yield sse_event({"error": {"code": "ai_provider_error", "message": str(exc)}})


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def validation_error(message: str):
    return jsonify({"error": {"code": "bad_request", "message": message}}), 400


def main():
    config = AgentConfig.from_env()
    if not is_loopback_addr(config.host):
        raise RuntimeError("AGENT_HOST must be a loopback address such as 127.0.0.1")

    app = create_app(config)
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    main()
