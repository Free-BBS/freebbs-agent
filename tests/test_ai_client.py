import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from freebbs_agent.ai_client import AIClientError, ChatClient
from freebbs_agent.config import AgentConfig
from freebbs_agent.server_settings import (
    SETTINGS_UNAVAILABLE_MESSAGE,
    ServerSettingsError,
    ServerSettingsSnapshot,
)


def make_config(**overrides):
    values = {
        "api_key": "static-key",
        "base_url": "https://static.example.test/v1",
        "model": "static-model",
        "host": "127.0.0.1",
        "port": 5001,
        "request_timeout_seconds": 5,
        "system_prompt": "Test system prompt.",
        "course_materials_root": "/srv/static-materials",
    }
    values.update(overrides)
    return AgentConfig(**values)


def make_snapshot(*, revision="1", api_key="managed-key", model="managed-model"):
    return ServerSettingsSnapshot(
        api_key=api_key,
        base_url=f"https://{revision}.models.example.test/v1",
        model=model,
        course_materials_root="/srv/managed-materials",
        revision=revision,
    )


class SequenceSettingsProvider:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = 0

    def get_snapshot(self):
        snapshot = self.snapshots[min(self.calls, len(self.snapshots) - 1)]
        self.calls += 1
        if isinstance(snapshot, Exception):
            raise snapshot
        return snapshot


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **payload):
        self.calls.append(payload)
        if payload.get("stream"):
            return iter(
                [
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="你"))]
                    ),
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="好"))]
                    ),
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="pong"),
                    finish_reason="stop",
                )
            ],
            model=payload["model"],
        )


class FailingCompletions:
    def create(self, **_payload):
        raise RuntimeError("Incorrect API key provided: managed-key-must-not-leak")


class FailingOpenAIClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FailingCompletions())


class FakeOpenAIClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class RecordingClientFactory:
    def __init__(self):
        self.calls = []
        self.clients = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        client = FakeOpenAIClient()
        self.clients.append(client)
        return client


class ChatClientSettingsTest(unittest.TestCase):
    def test_each_chat_reads_one_snapshot_and_reuses_client_for_same_revision(self):
        snapshot = make_snapshot()
        provider = SequenceSettingsProvider([snapshot, snapshot])
        factory = RecordingClientFactory()
        client = ChatClient(
            make_config(),
            settings_provider=provider,
            client_factory=factory,
        )

        first = client.chat([{"role": "user", "content": "first"}])
        second = client.chat([{"role": "user", "content": "second"}])

        self.assertEqual(first["answer"], "pong")
        self.assertEqual(second["answer"], "pong")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(factory.calls[0]["api_key"], "managed-key")
        self.assertEqual(factory.calls[0]["base_url"], snapshot.base_url)
        self.assertEqual(len(factory.clients[0].completions.calls), 2)
        self.assertEqual(
            factory.clients[0].completions.calls[0]["model"],
            "managed-model",
        )

    def test_revision_change_rebuilds_client_and_uses_matching_snapshot(self):
        first_snapshot = make_snapshot(revision="1", api_key="first-key", model="first-model")
        second_snapshot = make_snapshot(revision="2", api_key="second-key", model="second-model")
        provider = SequenceSettingsProvider([first_snapshot, second_snapshot])
        factory = RecordingClientFactory()
        client = ChatClient(
            make_config(),
            settings_provider=provider,
            client_factory=factory,
        )

        client.chat([{"role": "user", "content": "first"}])
        client.chat([{"role": "user", "content": "second"}])

        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(factory.calls[0]["api_key"], "first-key")
        self.assertEqual(factory.calls[1]["api_key"], "second-key")
        self.assertEqual(
            factory.clients[0].completions.calls[0]["model"],
            "first-model",
        )
        self.assertEqual(
            factory.clients[1].completions.calls[0]["model"],
            "second-model",
        )

    def test_same_revision_with_changed_secret_rebuilds_client(self):
        first_snapshot = make_snapshot(revision="7", api_key="first-key")
        second_snapshot = make_snapshot(revision="7", api_key="rotated-key")
        provider = SequenceSettingsProvider([first_snapshot, second_snapshot])
        factory = RecordingClientFactory()
        client = ChatClient(
            make_config(),
            settings_provider=provider,
            client_factory=factory,
        )

        client.chat([{"role": "user", "content": "first"}])
        client.chat([{"role": "user", "content": "second"}])

        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(factory.calls[0]["api_key"], "first-key")
        self.assertEqual(factory.calls[1]["api_key"], "rotated-key")

    def test_stream_holds_one_snapshot_for_the_entire_stream(self):
        provider = SequenceSettingsProvider(
            [
                make_snapshot(revision="1", model="stream-model"),
                make_snapshot(revision="2", model="later-model"),
            ]
        )
        factory = RecordingClientFactory()
        client = ChatClient(
            make_config(),
            settings_provider=provider,
            client_factory=factory,
        )

        chunks = list(client.stream_chat([{"role": "user", "content": "stream"}]))

        self.assertEqual(chunks, ["你", "好"])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(
            factory.clients[0].completions.calls[0]["model"],
            "stream-model",
        )

    def test_provider_failure_is_sanitized_and_never_falls_back_to_static_key(self):
        provider = SequenceSettingsProvider([ServerSettingsError(invalidate_cache=True)])
        factory = RecordingClientFactory()
        client = ChatClient(
            make_config(api_key="must-not-be-used"),
            settings_provider=provider,
            client_factory=factory,
        )

        with self.assertRaises(AIClientError) as raised:
            client.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(str(raised.exception), SETTINGS_UNAVAILABLE_MESSAGE)
        self.assertNotIn("must-not-be-used", repr(raised.exception))
        self.assertEqual(factory.calls, [])

    def test_model_provider_errors_do_not_expose_managed_key_details(self):
        provider = SequenceSettingsProvider(
            [make_snapshot(api_key="managed-key-must-not-leak")]
        )
        client = ChatClient(
            make_config(),
            settings_provider=provider,
            client_factory=lambda **_kwargs: FailingOpenAIClient(),
        )

        with self.assertRaises(AIClientError) as raised:
            client.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(str(raised.exception), "AI provider request failed")
        self.assertNotIn("managed-key-must-not-leak", repr(raised.exception))

    def test_static_environment_configuration_remains_compatible(self):
        factory = RecordingClientFactory()
        client = ChatClient(make_config(), client_factory=factory)

        result = client.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(result["answer"], "pong")
        self.assertEqual(factory.calls[0]["api_key"], "static-key")
        self.assertEqual(factory.calls[0]["base_url"], "https://static.example.test/v1")
        self.assertEqual(
            factory.clients[0].completions.calls[0]["model"],
            "static-model",
        )

    def test_config_requires_socket_and_token_to_be_set_together(self):
        base_env = {
            "AGENT_API_KEY": "static-key",
            "AGENT_SETTINGS_SOCKET": "/run/free-bbs/agent-config.sock",
            "AGENT_SERVICE_TOKEN": "service-token",
        }
        with patch.dict(os.environ, base_env, clear=True):
            self.assertTrue(AgentConfig.from_env().server_settings_enabled)

        with patch.dict(
            os.environ,
            {"AGENT_API_KEY": "static-key", "AGENT_SETTINGS_SOCKET": base_env["AGENT_SETTINGS_SOCKET"]},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must be configured together"):
                AgentConfig.from_env()

        with patch.dict(
            os.environ,
            {"AGENT_API_KEY": "static-key", "AGENT_SERVICE_TOKEN": "service-token"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must be configured together"):
                AgentConfig.from_env()

        with patch.dict(os.environ, {"AGENT_API_KEY": "static-key"}, clear=True):
            self.assertFalse(AgentConfig.from_env().server_settings_enabled)


if __name__ == "__main__":
    unittest.main()
