import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from freebbs_agent.config import AgentConfig
from freebbs_agent.online_router import OnlineAgentRouter
from freebbs_agent.rag.paths import (
    resolve_configured_rag_store_paths,
    resolve_under_course_root,
)
from freebbs_agent.rag.preflight import validate_rag_store_files
from freebbs_agent.server_settings import ServerSettingsError


def make_config(*, root: str = "", socket_path: str | None = None) -> AgentConfig:
    return AgentConfig(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        host="127.0.0.1",
        port=5001,
        request_timeout_seconds=5,
        system_prompt="test",
        course_materials_root=root,
        settings_socket_path=socket_path,
        agent_service_token="test-service-token" if socket_path else None,
        rag_index_path="data/rag/index.faiss",
        rag_metadata_path="data/rag/metadata.jsonl",
    )


class RagPathTest(unittest.TestCase):
    def test_resolves_relative_path_inside_course_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / "data" / "rag" / "index.faiss"

            self.assertEqual(
                resolve_under_course_root("data/rag/index.faiss", temp_dir),
                str(expected.resolve()),
            )

    def test_rejects_parent_traversal_outside_course_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            course_root = Path(temp_dir) / "courses"
            course_root.mkdir()

            with self.assertRaisesRegex(ValueError, "escapes the course materials root"):
                resolve_under_course_root("../outside/index.faiss", str(course_root))

    def test_rejects_symlink_escape_outside_course_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            course_root = Path(temp_dir) / "courses"
            outside_root = Path(temp_dir) / "outside"
            course_root.mkdir()
            outside_root.mkdir()
            (course_root / "escape").symlink_to(outside_root, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "escapes the course materials root"):
                resolve_under_course_root("escape/index.faiss", str(course_root))

    def test_preserves_absolute_paths_for_static_compatibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            absolute_path = str(Path(temp_dir) / "index.faiss")

            self.assertEqual(
                resolve_under_course_root(absolute_path, "/another/course/root"),
                absolute_path,
            )

    def test_online_router_falls_back_when_relative_store_escapes_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            course_root = Path(temp_dir) / "courses"
            course_root.mkdir()
            config = replace(
                make_config(root=str(course_root)),
                rag_enabled=True,
                rag_index_path="../outside/index.faiss",
            )
            chat_client = SimpleNamespace(
                course_materials_root=lambda: str(course_root),
            )

            decision = OnlineAgentRouter(config, chat_client).route(
                SimpleNamespace(messages=[]),
            )

            self.assertEqual(decision.agent, "general_chat")
            self.assertEqual(decision.mode, "fallback")

    @patch("freebbs_agent.rag.paths.ServerSettingsProvider")
    def test_managed_root_resolves_relative_store_paths(self, provider_class):
        provider_class.return_value.get_snapshot.return_value = SimpleNamespace(
            course_materials_root="/srv/managed-course-materials"
        )

        self.assertEqual(
            resolve_configured_rag_store_paths(
                make_config(socket_path="/run/free-bbs/agent-config.sock")
            ),
            (
                "/srv/managed-course-materials/data/rag/index.faiss",
                "/srv/managed-course-materials/data/rag/metadata.jsonl",
            ),
        )
        provider_class.assert_called_once_with(
            "/run/free-bbs/agent-config.sock",
            "test-service-token",
            timeout_seconds=2.0,
            cache_ttl_seconds=30.0,
            stale_ttl_seconds=300.0,
        )

    @patch("freebbs_agent.rag.paths.ServerSettingsProvider")
    def test_preflight_checks_files_under_managed_root(self, provider_class):
        with tempfile.TemporaryDirectory() as temp_dir:
            provider_class.return_value.get_snapshot.return_value = SimpleNamespace(
                course_materials_root=temp_dir
            )
            index_path = Path(temp_dir) / "data/rag/index.faiss"
            metadata_path = Path(temp_dir) / "data/rag/metadata.jsonl"
            index_path.parent.mkdir(parents=True)
            index_path.touch()
            metadata_path.touch()

            self.assertEqual(
                validate_rag_store_files(
                    make_config(socket_path="/run/free-bbs/agent-config.sock")
                ),
                (str(index_path.resolve()), str(metadata_path.resolve())),
            )

    @patch("freebbs_agent.rag.paths.ServerSettingsProvider")
    def test_managed_settings_failure_does_not_use_static_root(
        self, provider_class
    ):
        provider_class.return_value.get_snapshot.side_effect = ServerSettingsError()

        with self.assertRaisesRegex(
            RuntimeError, "server-managed model configuration is unavailable"
        ):
            resolve_configured_rag_store_paths(
                make_config(
                    root="/srv/unsafe-static-fallback",
                    socket_path="/run/free-bbs/agent-config.sock",
                )
            )


if __name__ == "__main__":
    unittest.main()
