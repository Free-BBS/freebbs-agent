from pathlib import Path
import tempfile
import unittest

from freebbs_agent.rag.ingest import load_documents_from_directory


class RagIngestTest(unittest.TestCase):
    def test_source_prefix_prevents_cross_directory_document_id_collisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text(
                "shared filename with useful content",
                encoding="utf-8",
            )

            first = load_documents_from_directory(root, source_prefix="source-a")
            second = load_documents_from_directory(root, source_prefix="source-b")

            self.assertEqual(first[0].source, "source-a/README.md")
            self.assertEqual(second[0].source, "source-b/README.md")
            self.assertNotEqual(first[0].doc_id, second[0].doc_id)


if __name__ == "__main__":
    unittest.main()
