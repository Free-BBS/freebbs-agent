import os
import tempfile
import unittest

from freebbs_agent.agent_tools import ToolError, execute_sqlite


class AgentToolsTest(unittest.TestCase):
    def test_execute_sqlite_read_only_query(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            execute_sqlite(path, "CREATE TABLE courses (id INTEGER PRIMARY KEY, name TEXT)", read_only=False)
            execute_sqlite(path, "INSERT INTO courses (name) VALUES (?)", ["signals"], read_only=False)

            result = execute_sqlite(path, "SELECT id, name FROM courses WHERE name = ?", ["signals"])

            self.assertEqual(result.rows, [{"id": 1, "name": "signals"}])
        finally:
            os.unlink(path)

    def test_execute_sqlite_rejects_writes_by_default(self):
        with self.assertRaises(ToolError):
            execute_sqlite(":memory:", "DELETE FROM courses")


if __name__ == "__main__":
    unittest.main()
