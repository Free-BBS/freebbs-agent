import unittest

from freebbs_agent.rag.keyword_search import BM25Retriever, tokenize


class KeywordSearchTest(unittest.TestCase):
    def test_tokenize_keeps_english_terms_and_chinese_bigrams(self):
        tokens = tokenize("Dijkstra解决单源最短路径")
        self.assertIn("dijkstra", tokens)
        self.assertIn("单源", tokens)
        self.assertIn("最短", tokens)
        self.assertIn("路径", tokens)

    def test_bm25_prefers_exact_course_terms(self):
        retriever = BM25Retriever(
            [
                {
                    "source": "graph.md",
                    "text": "Dijkstra 算法解决带权图的单源最短路径问题。",
                },
                {
                    "source": "sorting.md",
                    "text": "快速排序采用分治策略处理数组。",
                },
            ]
        )
        results = retriever.search("Dijkstra 单源最短路径", top_k=2)
        self.assertTrue(results)
        self.assertEqual(results[0][0], 0)

    def test_bm25_returns_empty_for_unmatched_query(self):
        retriever = BM25Retriever([{"source": "signals.md", "text": "傅里叶变换与频域分析"}])
        self.assertEqual(retriever.search("database transaction", top_k=3), [])


if __name__ == "__main__":
    unittest.main()
