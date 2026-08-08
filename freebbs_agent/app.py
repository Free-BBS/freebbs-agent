from __future__ import annotations

import json

from flask import Flask, Response, jsonify, request, stream_with_context

from .agent_utils import AgentInvocation, ChatOptions
from .agents import create_default_mux
from .ai_client import AIClientError, ChatClient
from .config import AgentConfig
from .dev_page import DEV_AGENT_TEST_HTML, build_scenario_test_page
from .navigation_dev_page import NAVIGATION_AGENT_TEST_HTML
from .security import add_local_cors_headers, is_loopback_addr, reject_non_loopback_requests
from .info_agent import InfoAgentClient, TrustedContextError, trusted_context_from_headers


def create_app(
    config: AgentConfig | None = None,
    chat_client: ChatClient | None = None,
    agent_mux=None,
    info_agent_client: InfoAgentClient | None = None,
) -> Flask:
    app_config = config or AgentConfig.from_env()
    app = Flask(__name__)
    app.config["AGENT_CONFIG"] = app_config
    app.chat_client = chat_client or ChatClient(app_config)  # type: ignore[attr-defined]
    app.info_agent_client = info_agent_client or InfoAgentClient(app_config)  # type: ignore[attr-defined]
    app.agent_mux = agent_mux or create_default_mux(  # type: ignore[attr-defined]
        app_config,
        app.chat_client,
        app.info_agent_client,
    )

    app.before_request(reject_non_loopback_requests)
    app.after_request(add_local_cors_headers)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "freebbs-agent"})

    @app.get("/dev/agent-test")
    def dev_agent_test():
        return Response(DEV_AGENT_TEST_HTML, mimetype="text/html")

    scenario_pages = {
        "/dev/general-test": (
            "General Agent 测试",
            "通用问答 Agent 独立测试页",
            "general",
            "general_test",
            "解释一下傅里叶变换在电子信息知识体系里的位置。",
        ),
        "/dev/rag-test": (
            "RAG Agent 测试",
            "课程资料检索与引用独立测试页",
            "rag",
            "rag_test",
            "帮我检索信号与系统的课程资料。",
        ),
        "/dev/comment-test": (
            "Comment Agent 测试",
            "评论区 @Max 回复独立测试页",
            "comment",
            "comment_test",
            "@max 这个结论为什么成立？",
        ),
        "/dev/course-graph-test": (
            "课程图谱场景测试",
            "课程关系、先修知识和学习路径测试页",
            "general",
            "navigation_course_graph",
            "信号与系统需要哪些前置知识？",
        ),
        "/dev/project-test": (
            "PBL 项目场景测试",
            "项目选题、组队和实践方向测试页",
            "general",
            "navigation_pbl",
            "我想找一个 FPGA 项目和队友。",
        ),
        "/dev/learning-profile-test": (
            "学习印记场景测试",
            "学习轨迹、能力画像和复盘测试页",
            "general",
            "navigation_learning_profile",
            "帮我分析当前学习进度和薄弱点。",
        ),
    }

    def render_scenario_page(path: str):
        title, description, agent, source, message = scenario_pages[path]
        return Response(
            build_scenario_test_page(
                title=title,
                description=description,
                agent=agent,
                source=source,
                default_message=message,
            ),
            mimetype="text/html",
        )

    for index, path in enumerate(scenario_pages):
        app.add_url_rule(
            path,
            endpoint=f"dev_scenario_test_{index}",
            view_func=lambda path=path: render_scenario_page(path),
            methods=["GET"],
        )

    @app.get("/dev/info-test")
    def dev_info_test():
        """Send developers to the existing Info Sub-Agent visual console."""
        target = app_config.info_agent_base_url or "http://127.0.0.1:4310"
        return Response(
            (
                "<!doctype html><meta charset='utf-8'>"
                "<title>Info Agent 测试</title>"
                f"<p>正在打开 <a href='{target}'>{target}</a>…</p>"
                f"<script>location.replace({json.dumps(target)});</script>"
            ),
            mimetype="text/html",
        )

    @app.get("/dev/navigation-test")
    def dev_navigation_test():
        return Response(NAVIGATION_AGENT_TEST_HTML, mimetype="text/html")

    @app.post("/api/v1/chat")
    def chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return validation_error("request body must be a JSON object")

        try:
            invocation = build_invocation(payload, app_config)
            selected_agent = app.agent_mux.select(invocation)  # type: ignore[attr-defined]
            if selected_agent.name == "info":
                invocation.payload["_trusted_context"] = trusted_context_from_headers(
                    request.headers,
                    app_config.freebbs_agent_internal_token,
                )
            elif selected_agent.name == "navigation" and request.headers.get(
                "X-FreeBBS-Internal-Token"
            ):
                # Navigation may delegate to Info. Only accept identity supplied by
                # an authenticated backend; RAG/navigation-only calls need no identity.
                invocation.payload["_trusted_context"] = trusted_context_from_headers(
                    request.headers,
                    app_config.freebbs_agent_internal_token,
                )
        except TrustedContextError as exc:
            return jsonify({"error": {"code": exc.code, "message": str(exc)}}), exc.status_code
        except ValueError as exc:
            return validation_error(str(exc))

        if invocation.options.stream:
            return Response(
                stream_with_context(
                    sse_chat_stream(selected_agent, invocation)
                ),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        try:
            result = selected_agent.run(invocation)
        except ValueError as exc:
            return validation_error(str(exc))
        except AIClientError as exc:
            return jsonify({"error": {"code": "ai_provider_error", "message": str(exc)}}), 502

        return jsonify(result)

    @app.post("/api/v1/info/jobs/get")
    def get_info_job():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return validation_error("request body must be a JSON object")
        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or not job_id.startswith("job_"):
            return validation_error("job_id must be a valid Info Agent job ID")
        try:
            trusted_context = trusted_context_from_headers(
                request.headers,
                app_config.freebbs_agent_internal_token,
            )
            envelope = app.info_agent_client.get_job(job_id, trusted_context)  # type: ignore[attr-defined]
        except TrustedContextError as exc:
            return jsonify({"error": {"code": exc.code, "message": str(exc)}}), exc.status_code
        except Exception:
            return jsonify({"error": {"code": "info_agent_unavailable", "message": "Info Agent service unavailable."}}), 502

        status = 202 if envelope.get("status") == "pending" else 200
        return jsonify(envelope), status

    return app


def build_invocation(payload: dict, config: AgentConfig) -> AgentInvocation:
    messages = normalize_messages(payload, config.system_prompt)
    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("model must be a string")

    return AgentInvocation(
        payload=payload,
        messages=messages,
        options=ChatOptions(
            model=model,
            temperature=optional_float(payload, "temperature"),
            max_tokens=optional_int(payload, "max_tokens"),
            stream=optional_bool(payload, "stream"),
        ),
    )


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


def sse_chat_stream(agent, invocation):
    try:
        for chunk in agent.stream(invocation):
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
