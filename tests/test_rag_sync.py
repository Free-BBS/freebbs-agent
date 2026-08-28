import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from freebbs_agent.config import AgentConfig
from freebbs_agent.rag.course_snapshot import (
    CourseSnapshotError,
    course_snapshot_documents,
    validate_course_snapshot,
)
from freebbs_agent.rag.manifest import (
    active_store_paths,
    load_rag_index_manifest,
    write_rag_index_manifest,
)


class RagCourseSnapshotTest(unittest.TestCase):
    def test_rag_enabled_accepts_trimmed_true_environment_value(self):
        with patch.dict(
            "os.environ",
            {
                "RAG_ENABLED": " true ",
                "AGENT_SETTINGS_SOCKET": "",
                "AGENT_SERVICE_TOKEN": "",
            },
            clear=False,
        ):
            self.assertTrue(AgentConfig.from_env().rag_enabled)

    def test_course_snapshot_connection_can_be_separate_from_managed_settings(self):
        with patch.dict(
            "os.environ",
            {
                "AGENT_SETTINGS_SOCKET": "",
                "AGENT_SERVICE_TOKEN": "",
                "RAG_COURSE_SNAPSHOT_SOCKET": "/tmp/freebbs-rag-test.sock",
                "RAG_COURSE_SNAPSHOT_TOKEN": "local-test-token",
            },
            clear=False,
        ):
            config = AgentConfig.from_env()
            self.assertFalse(config.server_settings_enabled)
            self.assertEqual(
                config.rag_course_snapshot_socket_path,
                "/tmp/freebbs-rag-test.sock",
            )
            self.assertEqual(config.rag_course_snapshot_token, "local-test-token")

    def test_converts_course_sections_and_relations_to_stable_documents(self):
        snapshot = validate_course_snapshot(
            {
                "revision": 12,
                "documents": [
                    {
                        "courseId": 7,
                        "courseSlug": "signals",
                        "courseName": "信号系统",
                        "courseSummary": "课程摘要",
                        "nodeId": "SS-01",
                        "title": "连续时间信号",
                        "summary": "知识点摘要",
                        "knowledgeMarkdown": "傅里叶变换正文",
                        "basicInfoMarkdown": "难度：2",
                        "applicationsMarkdown": "频谱分析",
                        "updatedAt": "2026-08-28T00:00:00Z",
                        "relations": [
                            {
                                "direction": "incoming",
                                "type": "ordered",
                                "nodeId": "MATH-01",
                                "title": "复指数",
                            }
                        ],
                    }
                ],
            }
        )

        documents, metadata = course_snapshot_documents(
            snapshot,
            web_base_url="https://www.free-bbs.cn",
        )

        self.assertEqual(len(documents), 4)
        overview = next(item for item in documents if item.doc_id.endswith(":overview"))
        self.assertIn("前置知识：复指数（MATH-01）", overview.text)
        knowledge = next(item for item in documents if item.doc_id.endswith(":knowledge"))
        self.assertIn("课程：信号系统", knowledge.text)
        self.assertEqual(
            knowledge.source,
            "https://www.free-bbs.cn/knowledge?course=signals&point=SS-01",
        )
        self.assertEqual(metadata[knowledge.doc_id]["course_slug"], "signals")
        self.assertEqual(metadata[knowledge.doc_id]["snapshot_revision"], "12")

    def test_rejects_snapshot_without_revision(self):
        with self.assertRaises(CourseSnapshotError):
            validate_course_snapshot({"documents": []})


class RagManifestTest(unittest.TestCase):
    def test_writes_and_resolves_versioned_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            version_dir = root / "versions/v12"
            version_dir.mkdir(parents=True)
            index_path = version_dir / "index.faiss"
            metadata_path = version_dir / "metadata.jsonl"
            index_path.touch()
            metadata_path.touch()
            manifest_path = root / "current.json"

            write_rag_index_manifest(
                str(manifest_path),
                {
                    "version": "v12",
                    "revision": 12,
                    "index_path": str(index_path),
                    "metadata_path": str(metadata_path),
                    "document_count": 2,
                    "chunk_count": 4,
                },
            )

            manifest = load_rag_index_manifest(str(manifest_path))
            self.assertEqual(manifest.revision, "12")
            self.assertEqual(manifest.chunk_count, 4)
            self.assertEqual(
                active_store_paths(
                    str(manifest_path),
                    ("fallback.index", "fallback.metadata"),
                ),
                ((str(index_path.resolve()), str(metadata_path.resolve())), "v12"),
            )

    def test_uses_static_store_before_first_synchronized_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback = ("index.faiss", "metadata.jsonl")
            self.assertEqual(
                active_store_paths(str(Path(temp_dir) / "missing.json"), fallback),
                (fallback, "static"),
            )


if __name__ == "__main__":
    unittest.main()
