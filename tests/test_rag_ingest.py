import json
import tempfile
import unittest
from pathlib import Path

from freebbs_agent.rag.ingest import extract_text, load_documents_from_directory


class RagIngestTest(unittest.TestCase):
    def test_extracts_markdown_cells_from_notebook(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "lesson.ipynb"
            path.write_text(
                json.dumps(
                    {
                        "cells": [
                            {"cell_type": "markdown", "source": ["# Sampling\n", "Nyquist theorem"]},
                            {"cell_type": "code", "source": ["print('not indexed')"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            text = extract_text(path)
            self.assertIn("Nyquist theorem", text)
            self.assertNotIn("not indexed", text)

    def test_source_prefix_prevents_cross_repository_collisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "README.md"
            path.write_text("A sufficiently long signals and systems lesson.", encoding="utf-8")
            first = load_documents_from_directory(temp_dir, source_prefix="course-a")
            second = load_documents_from_directory(temp_dir, source_prefix="course-b")
            self.assertNotEqual(first[0].doc_id, second[0].doc_id)
            self.assertEqual(first[0].source, "course-a/README.md")


if __name__ == "__main__":
    unittest.main()
