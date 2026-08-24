import unittest

from freebbs_agent.course_catalog import infer_course, match_named_course


class CourseCatalogTest(unittest.TestCase):
    def test_matches_explicit_course_aliases(self):
        self.assertEqual(match_named_course("我想学信号与系统")["slug"], "signals")
        self.assertEqual(match_named_course("打开数电课程")["slug"], "digital")

    def test_does_not_guess_for_generic_navigation(self):
        self.assertIsNone(match_named_course("带我去课程学习"))
        self.assertIsNone(infer_course(["帮我理解这个知识点"]))

    def test_infers_course_from_knowledge_topic(self):
        result = infer_course(["傅里叶变换的时域和频域关系是什么？"])

        self.assertEqual(result["slug"], "signals")
        self.assertEqual(result["board"], "signal")

    def test_longest_explicit_name_wins_for_shared_circuit_words(self):
        self.assertEqual(match_named_course("我想学习数字电路")["slug"], "digital")


if __name__ == "__main__":
    unittest.main()
