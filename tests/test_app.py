import unittest

from freebbs_agent.app import create_app
from freebbs_agent.config import AgentConfig


class FakeChatClient:
    def __init__(self):
        self.calls = []

    def chat(self, messages, *, model=None, temperature=None, max_tokens=None):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return {"answer": "pong", "model": model or "test-model", "finish_reason": "stop"}

    def stream_chat(self, messages, *, model=None, temperature=None, max_tokens=None):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
        )
        yield "你"
        yield "好"


class AppTest(unittest.TestCase):
    def setUp(self):
        self.chat_client = FakeChatClient()
        config = AgentConfig(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="test-model",
            host="127.0.0.1",
            port=5001,
            request_timeout_seconds=5,
            system_prompt="Default test prompt.",
        )
        self.client = create_app(config, self.chat_client).test_client()

    def test_health(self):
        response = self.client.get("/health", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_rejects_non_loopback(self):
        response = self.client.get("/health", environ_base={"REMOTE_ADDR": "10.0.0.2"})
        self.assertEqual(response.status_code, 403)

    def test_chat_accepts_message(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"message": "hello", "system": "You are helpful.", "temperature": 0.2},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["answer"], "pong")
        self.assertEqual(
            self.chat_client.calls[0]["messages"],
            [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hello"},
            ],
        )

    def test_chat_injects_default_system_prompt(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"message": "hello"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.chat_client.calls[0]["messages"],
            [
                {"role": "system", "content": "Default test prompt."},
                {"role": "user", "content": "hello"},
            ],
        )

    def test_chat_messages_inject_default_system_prompt_when_missing(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.chat_client.calls[0]["messages"],
            [
                {"role": "system", "content": "Default test prompt."},
                {"role": "user", "content": "hello"},
            ],
        )

    def test_chat_messages_keep_request_system_prompt(self):
        response = self.client.post(
            "/api/v1/chat",
            json={
                "messages": [
                    {"role": "system", "content": "Request prompt."},
                    {"role": "user", "content": "hello"},
                ]
            },
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.chat_client.calls[0]["messages"],
            [
                {"role": "system", "content": "Request prompt."},
                {"role": "user", "content": "hello"},
            ],
        )

    def test_chat_validates_body(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"message": ""},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 400)

    def test_chat_streams_sse_characters(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"message": "hello", "stream": True},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "text/event-stream; charset=utf-8")
        body = response.get_data(as_text=True)
        self.assertIn('data: {"delta": "你"}', body)
        self.assertIn('data: {"delta": "好"}', body)
        self.assertIn('data: {"done": true}', body)

    def test_chat_routes_comment_mentions_to_comment_agent(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"message": "@max 这个问题怎么发讨论区？", "source": "comment"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        messages = self.chat_client.calls[0]["messages"]
        self.assertIn("评论区 @Max 场景", messages[0]["content"])

    def test_chat_rejects_unknown_agent(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"message": "hello", "agent": "missing_agent"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "bad_request")


if __name__ == "__main__":
    unittest.main()
