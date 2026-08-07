from __future__ import annotations

import hmac
import json
import re
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

from .agent_tools import ToolError, http_request
from .agent_utils import AgentInvocation, ChatClient, FreeBBSAgent
from .config import AgentConfig


ALLOWED_INFO_PERMISSIONS = {"web_learning:read", "thu_info:read"}
INFO_QUERY_PATTERN = re.compile(
    r"网络学堂|课程公告|最新公告|我的课程|我的课表|校内通知|讲座通知|活动通知|thu\s*info",
    re.IGNORECASE,
)


class TrustedContextError(ValueError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def trusted_context_from_headers(
    headers: Mapping[str, str],
    expected_token: str | None,
) -> dict[str, Any]:
    """Build model-hidden identity context from an authenticated backend request."""

    if not expected_token:
        raise TrustedContextError(
            "trusted_proxy_disabled",
            "FREEBBS_AGENT_INTERNAL_TOKEN is not configured.",
            503,
        )

    received_token = headers.get("X-FreeBBS-Internal-Token", "")
    if not hmac.compare_digest(received_token.encode(), expected_token.encode()):
        raise TrustedContextError(
            "unauthorized_trusted_context",
            "Trusted backend authentication failed.",
            401,
        )

    uid = headers.get("X-FreeBBS-UID", "").strip()
    student_no = headers.get("X-FreeBBS-Student-No", "").strip() or None
    session_id = headers.get("X-FreeBBS-Session-ID", "").strip() or None
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", uid):
        raise TrustedContextError("invalid_trusted_context", "Invalid trusted UID.", 400)
    if student_no and not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", student_no):
        raise TrustedContextError("invalid_trusted_context", "Invalid trusted student number.", 400)
    if session_id and not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", session_id):
        raise TrustedContextError("invalid_trusted_context", "Invalid trusted session ID.", 400)

    requested_permissions = {
        item.strip()
        for item in headers.get("X-FreeBBS-Permissions", "").split(",")
        if item.strip()
    }
    permissions = sorted(requested_permissions & ALLOWED_INFO_PERMISSIONS)
    return {
        "uid": uid,
        "student_no": student_no,
        "session_id": session_id,
        "permissions": permissions,
    }


class InfoAgentClient:
    """Server-to-server client for the standard subagent-eeinfo protocol."""

    def __init__(self, config: AgentConfig) -> None:
        self.base_url = config.info_agent_base_url.rstrip("/")
        self.internal_token = config.info_agent_internal_token
        self.timeout_seconds = config.info_agent_timeout_seconds
        self.auto_authenticate = config.info_agent_auto_authenticate
        self._manifest_checked = False

    def manifest(self) -> dict[str, Any]:
        return self._request("GET", "/internal/tools/manifest")

    def execute(self, goal: str, trusted_context: dict[str, Any]) -> dict[str, Any]:
        self._ensure_manifest()
        tool_call_id = f"call_{uuid.uuid4()}"
        return self._request(
            "POST",
            "/internal/tools/execute",
            {
                "protocol_version": "1.0",
                "tool_call": {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": "info_agent",
                        "arguments": json.dumps({"goal": goal}, ensure_ascii=False),
                    },
                },
                "execution_options": {
                    "sources": ["web_learning", "thu_info"],
                    "refresh_policy": "if_stale",
                    "max_results": 20,
                    "max_tool_calls": 8,
                    "timeout_ms": int(self.timeout_seconds * 1000),
                    "auto_authenticate": self.auto_authenticate,
                },
                "trusted_context": trusted_context,
            },
        )

    def get_job(self, job_id: str, trusted_context: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/jobs/get",
            {"job_id": job_id, "trusted_context": trusted_context},
        )

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.internal_token:
            raise ToolError("INFO_AGENT_INTERNAL_TOKEN is not configured")
        result = http_request(
            f"{self.base_url}{path}",
            method=method,
            headers={"Authorization": f"Bearer {self.internal_token}"},
            json_body=body,
            timeout_seconds=self.timeout_seconds,
        )
        if not isinstance(result.json, dict):
            raise ToolError("Info Agent returned a non-JSON response")
        return result.json

    def _ensure_manifest(self) -> None:
        if self._manifest_checked:
            return
        manifest = self.manifest()
        tools = manifest.get("tools")
        if manifest.get("protocol_version") != "1.0" or not isinstance(tools, list):
            raise ToolError("Info Agent returned an incompatible manifest")
        names = {
            item.get("function", {}).get("name")
            for item in tools
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        }
        if "info_agent" not in names:
            raise ToolError("Info Agent manifest does not expose info_agent")
        self._manifest_checked = True


class InfoAgentBridge(FreeBBSAgent):
    """Delegate course and campus information requests to subagent-eeinfo."""

    name = "info"
    aliases = {"info_agent", "eeinfo", "campus_info"}

    def __init__(
        self,
        config: AgentConfig,
        chat_client: ChatClient,
        info_client: InfoAgentClient | None = None,
    ) -> None:
        super().__init__(config, chat_client)
        self.info_client = info_client or InfoAgentClient(config)

    def can_handle(self, invocation: AgentInvocation) -> bool:
        requested_agent = invocation.payload.get("agent")
        if requested_agent == self.name or requested_agent in self.aliases:
            return True
        if requested_agent is not None:
            return False
        return self.config.info_agent_enabled and bool(INFO_QUERY_PATTERN.search(invocation.message))

    def run(self, invocation: AgentInvocation) -> dict[str, Any]:
        if not self.config.info_agent_enabled:
            return self._failure("Info Agent bridge is disabled.", "info_agent_disabled")
        trusted_context = invocation.payload.get("_trusted_context")
        if not isinstance(trusted_context, dict):
            return self._failure("缺少由主系统后端注入的可信用户身份。", "trusted_context_missing")

        try:
            envelope = self.info_client.execute(invocation.message, trusted_context)
        except ToolError as exc:
            return self._failure("Info Agent 服务暂时不可用。", "info_agent_unavailable", str(exc))
        return self.present_envelope(envelope)

    def stream(self, invocation: AgentInvocation) -> Iterator[str]:
        yield self.run(invocation)["answer"]

    @classmethod
    def present_envelope(cls, envelope: dict[str, Any]) -> dict[str, Any]:
        status = envelope.get("status", "failed")
        result = envelope.get("result") if isinstance(envelope.get("result"), dict) else None
        if result:
            answer = result.get("summary") or cls._default_answer(status)
        elif status == "pending":
            answer = "需要完成网络学堂认证；认证任务已由程序启动。"
        else:
            error = envelope.get("error") if isinstance(envelope.get("error"), dict) else {}
            answer = error.get("message") or cls._default_answer(status)

        return {
            "answer": answer,
            "agent": cls.name,
            "status": status,
            "request_id": envelope.get("request_id"),
            "tool_call_id": envelope.get("tool_call_id"),
            "tool_message": envelope.get("message"),
            "result": result,
            "execution": envelope.get("execution"),
            "required_action": envelope.get("required_action"),
            "model": "subagent-eeinfo",
            "finish_reason": "stop",
        }

    @staticmethod
    def _default_answer(status: str) -> str:
        return {
            "not_found": "没有查询到符合条件的信息。",
            "partial": "查询只完成了一部分，请查看返回的警告信息。",
            "failed": "Info Agent 未能完成本次查询。",
        }.get(status, "Info Agent 已返回结果。")

    @classmethod
    def _failure(cls, answer: str, code: str, detail: str | None = None) -> dict[str, Any]:
        return {
            "answer": answer,
            "agent": cls.name,
            "status": "failed",
            "error": {"code": code, "detail": detail},
            "model": "subagent-eeinfo",
            "finish_reason": "stop",
        }
