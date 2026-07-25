import unittest

from scripts.evaluate_rag_answers import fact_coverage, parse_json_object


class RagAnswerEvalTest(unittest.TestCase):
    def test_fact_coverage_counts_exact_normalized_phrases(self):
        result = fact_coverage(
            "Dijkstra 解决单源最短路径；Floyd解决全源最短路径。",
            ["Dijkstra 解决单源最短路径", "Floyd 解决全源最短路径", "Floyd 使用动态规划思想"],
        )
        self.assertEqual(result["exact_fact_hits"], 2)
        self.assertAlmostEqual(result["exact_fact_coverage"], 2 / 3)

    def test_parse_json_object_accepts_code_fence(self):
        self.assertEqual(parse_json_object('```json\n{"winner":"A"}\n```')["winner"], "A")


if __name__ == "__main__":
    unittest.main()
