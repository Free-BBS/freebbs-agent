import base64
import unittest
from types import SimpleNamespace

from freebbs_agent.agent_utils import AgentInvocation, ChatOptions
from freebbs_agent.ai_client import AIClientError, ChatClient
from freebbs_agent.config import AgentConfig
from freebbs_agent.image_generation import (
    IMAGE_PLACEHOLDER,
    parse_image_request,
    run_with_optional_image,
)


def make_config(**overrides):
    values = {
        "api_key": "test-key",
        "base_url": "https://models.example.test/v1",
        "model": "chat-model",
        "host": "127.0.0.1",
        "port": 5001,
        "request_timeout_seconds": 5,
        "system_prompt": "Test prompt.",
    }
    values.update(overrides)
    return AgentConfig(**values)


class FakeImageChatClient:
    def __init__(self, answer, *, fail=False):
        self.answer = answer
        self.fail = fail
        self.chat_calls = []
        self.image_calls = []

    def chat(self, messages, **_options):
        self.chat_calls.append(messages)
        return {"answer": self.answer, "model": "chat-model", "finish_reason": "stop"}

    def generate_image(self, prompt, *, size):
        self.image_calls.append({"prompt": prompt, "size": size})
        if self.fail:
            raise AIClientError("provider detail must not escape")
        return {
            "data_url": "data:image/png;base64,aW1hZ2U=",
            "model": "doubao-seedream-5-0",
        }


class FakeAgent:
    def __init__(self, answer, *, fail=False):
        self.config = make_config()
        self.chat_client = FakeImageChatClient(answer, fail=fail)

    def call_llm(self, messages, options):
        return self.chat_client.chat(messages, model=options.model)


def invocation(*, allowed=True, stream=False, reasoning_stream=False):
    return AgentInvocation(
        payload={
            "allow_image_generation": allowed,
            "reasoning_stream": reasoning_stream,
        },
        messages=[
            {"role": "system", "content": "System."},
            {"role": "user", "content": "请画一张图"},
        ],
        options=ChatOptions(stream=stream),
    )


class ImageGenerationTest(unittest.TestCase):
    def test_parses_one_strict_image_block(self):
        answer = (
            "说明。\n```max-image\n"
            '{"prompt":"教学插画","alt":"傅里叶变换示意图","aspect_ratio":"landscape"}'
            "\n```\n结束。"
        )
        replaced, request = parse_image_request(answer)
        self.assertIn(IMAGE_PLACEHOLDER, replaced)
        self.assertEqual(request.prompt, "教学插画")
        self.assertEqual(request.size, "2560x1440")

    def test_generates_only_when_allowed_and_requested(self):
        answer = (
            "这里是图：\n```max-image\n"
            '{"prompt":"简洁教学插画","alt":"教学图","aspect_ratio":"square"}'
            "\n```"
        )
        agent = FakeAgent(answer)
        result = run_with_optional_image(agent, invocation(), invocation().messages)
        self.assertEqual(len(agent.chat_client.image_calls), 1)
        self.assertIn(IMAGE_PLACEHOLDER, result["answer"])
        self.assertEqual(result["generated_images"][0]["model"], "doubao-seedream-5-0")
        self.assertIn("图片生成工具", agent.chat_client.chat_calls[0][0]["content"])

        disabled = FakeAgent(answer)
        untouched = run_with_optional_image(
            disabled, invocation(allowed=False), invocation(allowed=False).messages
        )
        self.assertEqual(untouched["answer"], answer)
        self.assertEqual(disabled.chat_client.image_calls, [])

        reasoning = FakeAgent(answer)
        streamed_result = run_with_optional_image(
            reasoning,
            invocation(stream=True, reasoning_stream=True),
            invocation(stream=True, reasoning_stream=True).messages,
        )
        self.assertEqual(len(reasoning.chat_client.image_calls), 1)
        self.assertEqual(streamed_result["image_generation"]["status"], "completed")

        raw_stream = FakeAgent(answer)
        untouched_stream = run_with_optional_image(
            raw_stream,
            invocation(stream=True),
            invocation(stream=True).messages,
        )
        self.assertEqual(untouched_stream["answer"], answer)
        self.assertEqual(raw_stream.chat_client.image_calls, [])

    def test_provider_failure_becomes_safe_user_message(self):
        answer = (
            "```max-image\n"
            '{"prompt":"一张图","alt":"图","aspect_ratio":"portrait"}'
            "\n```"
        )
        result = run_with_optional_image(
            FakeAgent(answer, fail=True), invocation(), invocation().messages
        )
        self.assertEqual(result["image_generation"]["status"], "failed")
        self.assertEqual(result["image_generation"]["reason"], "ai_provider_error")
        self.assertIn("暂时不可用", result["answer"])
        self.assertNotIn("provider detail", result["answer"])


class FakeImages:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"\x89PNG\r\n\x1a\nbody").decode())]
        )


class FakeOpenAIClient:
    def __init__(self):
        self.models = SimpleNamespace(
            list=lambda: SimpleNamespace(
                data=[SimpleNamespace(id="chat-model"), SimpleNamespace(id="doubao-seedream-5-0")]
            )
        )
        self.images = FakeImages()


class ChatClientImageTest(unittest.TestCase):
    def test_discovers_seedream_and_requests_base64(self):
        fake = FakeOpenAIClient()
        client = ChatClient(make_config(), client_factory=lambda **_kwargs: fake)
        result = client.generate_image("test", size="2048x2048")
        self.assertEqual(result["model"], "doubao-seedream-5-0")
        self.assertTrue(result["data_url"].startswith("data:image/png;base64,"))
        self.assertEqual(fake.images.calls[0]["response_format"], "b64_json")


if __name__ == "__main__":
    unittest.main()
