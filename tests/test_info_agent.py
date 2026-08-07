import unittest
from types import SimpleNamespace
from unittest.mock import patch

from freebbs_agent.agent_utils import AgentInvocation, ChatOptions
from freebbs_agent.app import create_app
from freebbs_agent.config import AgentConfig
from freebbs_agent.info_agent import (
    InfoAgentBridge,
    InfoAgentClient,
    TrustedContextError,
    trusted_context_from_headers,
)


def info_config(**overrides):
    values = {
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "model": "test-model",
        "host": "127.0.0.1",
        "port": 5001,
        "request_timeout_seconds": 5,
        "system_prompt": "Test prompt.",
        "info_agent_enabled": True,
        "info_agent_internal_token": "eeinfo-secret",
        "freebbs_agent_internal_token": "backend-secret",
    }
    values.update(overrides)
    return AgentConfig(**values)


class FakeChatClient:
    def chat(self, *args, **kwargs):
        return {"answer": "fallback", "model": "fake", "finish_reason": "stop"}

    def stream_chat(self, *args, **kwargs):
        yield "fallback"


class FakeInfoClient:
    def __init__(self, envelope=None):
        self.envelope = envelope or {
            "protocol_version": "1.0",
            "request_id": "req_test",
            "tool_call_id": "call_test",
            "tool_name": "info_agent",
            "status": "success",
            "message": {
                "role": "tool",
                "tool_call_id": "call_test",
                "name": "info_agent",
                "content": "{}",
            },
            "result": {
                "request_id": "req_test",
                "status": "success",
                "summary": "查询到两门课程。",
                "info": [],
            },
        }
        self.executions = []
        self.jobs = []

    def execute(self, goal, trusted_context):
        self.executions.append((goal, trusted_context))
        return self.envelope

    def get_job(self, job_id, trusted_context):
        self.jobs.append((job_id, trusted_context))
        return {"protocol_version": "1.0", "status": "pending", "execution": {"job_id": job_id}}


class InfoAgentBridgeTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeInfoClient()
        self.bridge = InfoAgentBridge(info_config(), FakeChatClient(), self.client)

    @staticmethod
    def invocation(message="查询我的网络学堂课程", agent="info"):
        return AgentInvocation(
            payload={
                "agent": agent,
                "message": message,
                "_trusted_context": {
                    "uid": "user_1",
                    "student_no": "20260001",
                    "session_id": "session_1",
                    "permissions": ["web_learning:read"],
                },
            },
            messages=[{"role": "user", "content": message}],
            options=ChatOptions(),
        )

    def test_explicit_and_clear_info_queries_route_to_bridge(self):
        self.assertTrue(self.bridge.can_handle(self.invocation()))
        automatic = self.invocation("信号与系统最新公告", agent=None)
        automatic.payload.pop("agent")
        self.assertTrue(self.bridge.can_handle(automatic))

    def test_does_not_capture_another_explicit_agent(self):
        self.assertFalse(
            self.bridge.can_handle(self.invocation("查询最近课程公告", agent="navigation"))
        )

    def test_bridge_calls_standard_info_service_without_identity_in_goal(self):
        result = self.bridge.run(self.invocation())
        self.assertEqual(result["answer"], "查询到两门课程。")
        self.assertEqual(result["status"], "success")
        goal, trusted_context = self.client.executions[0]
        self.assertEqual(goal, "查询我的网络学堂课程")
        self.assertEqual(trusted_context["uid"], "user_1")
        self.assertNotIn("20260001", goal)

    def test_pending_envelope_is_returned_to_orchestration_layer(self):
        pending_client = FakeInfoClient(
            {
                "status": "pending",
                "execution": {"job_id": "job_123", "state": "authenticating"},
                "required_action": {"type": "interactive_authentication"},
            }
        )
        bridge = InfoAgentBridge(info_config(), FakeChatClient(), pending_client)
        result = bridge.run(self.invocation())
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["execution"]["job_id"], "job_123")


class InfoAgentClientTest(unittest.TestCase):
    def test_validates_manifest_and_sends_standard_string_arguments(self):
        responses = [
            SimpleNamespace(
                json={
                    "protocol_version": "1.0",
                    "tools": [{"type": "function", "function": {"name": "info_agent"}}],
                }
            ),
            SimpleNamespace(json={"status": "success", "result": {"summary": "完成"}}),
        ]
        with patch("freebbs_agent.info_agent.http_request", side_effect=responses) as request_mock:
            client = InfoAgentClient(info_config())
            client.execute(
                "查询课程公告",
                {"uid": "user_1", "student_no": "20260001", "permissions": ["web_learning:read"]},
            )

        self.assertEqual(request_mock.call_count, 2)
        execute_body = request_mock.call_args_list[1].kwargs["json_body"]
        arguments = execute_body["tool_call"]["function"]["arguments"]
        self.assertIsInstance(arguments, str)
        self.assertIn("查询课程公告", arguments)


class TrustedContextTest(unittest.TestCase):
    def test_requires_backend_token_and_filters_permissions(self):
        context = trusted_context_from_headers(
            {
                "X-FreeBBS-Internal-Token": "backend-secret",
                "X-FreeBBS-UID": "user_1",
                "X-FreeBBS-Student-No": "20260001",
                "X-FreeBBS-Session-ID": "session_1",
                "X-FreeBBS-Permissions": "web_learning:read,admin,thu_info:read",
            },
            "backend-secret",
        )
        self.assertEqual(context["uid"], "user_1")
        self.assertEqual(context["permissions"], ["thu_info:read", "web_learning:read"])

    def test_rejects_forged_trusted_context(self):
        with self.assertRaises(TrustedContextError):
            trusted_context_from_headers(
                {"X-FreeBBS-Internal-Token": "wrong", "X-FreeBBS-UID": "victim"},
                "backend-secret",
            )


class InfoAgentAppTest(unittest.TestCase):
    def setUp(self):
        self.info_client = FakeInfoClient()
        self.app = create_app(
            info_config(),
            FakeChatClient(),
            info_agent_client=self.info_client,
        )
        self.client = self.app.test_client()
        self.headers = {
            "X-FreeBBS-Internal-Token": "backend-secret",
            "X-FreeBBS-UID": "user_1",
            "X-FreeBBS-Student-No": "20260001",
            "X-FreeBBS-Session-ID": "session_1",
            "X-FreeBBS-Permissions": "web_learning:read,thu_info:read",
        }

    def test_chat_injects_headers_as_model_hidden_context(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"agent": "info", "message": "查询我的课程"},
            headers=self.headers,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["agent"], "info")
        self.assertEqual(self.info_client.executions[0][1]["uid"], "user_1")

    def test_navigation_can_delegate_to_info_with_trusted_headers(self):
        response = self.client.post(
            "/api/v1/chat",
            json={
                "agent": "navigation",
                "execute_subagent": "auto",
                "message": "查询最近的课程公告和讲座通知",
            },
            headers=self.headers,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["agent"], "navigation")
        self.assertEqual(body["delegation"]["selected"], "info")
        self.assertEqual(body["subagent"]["agent"], "info")
        self.assertEqual(self.info_client.executions[0][1]["uid"], "user_1")

    def test_chat_rejects_frontend_identity_without_backend_token(self):
        response = self.client.post(
            "/api/v1/chat",
            json={
                "agent": "info",
                "message": "查询我的课程",
                "uid": "forged-user",
                "student_no": "20269999",
            },
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "unauthorized_trusted_context")

    def test_job_proxy_reuses_authenticated_identity(self):
        response = self.client.post(
            "/api/v1/info/jobs/get",
            json={"job_id": "job_123"},
            headers=self.headers,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.info_client.jobs[0][1]["uid"], "user_1")


if __name__ == "__main__":
    unittest.main()
