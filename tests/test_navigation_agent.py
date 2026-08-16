import unittest

from freebbs_agent.agent_utils import AgentInvocation, ChatOptions
from freebbs_agent.app import create_app
from freebbs_agent.config import AgentConfig
from freebbs_agent.navigation_agent import NavigationAgent


class UnusedChatClient:
    def chat(self, *args, **kwargs):
        raise AssertionError("NavigationAgent must not call the LLM")


class FakeNavigationChatClient:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return {
            "answer": (
                '{"intents":["course_graph"],"answer":"先从课程图谱确认信号与系统的前置知识。",'
                '"needs_clarification":false,"confidence":0.91,'
                '"reason_by_intent":{"course_graph":"能把当前课程与前置数学知识连接起来。"}}'
            ),
            "model": "fake-guide-model",
            "finish_reason": "stop",
        }

    def stream_chat(self, *args, **kwargs):
        raise AssertionError("NavigationAgent must not call the LLM")


class GeneralChatClient:
    def chat(self, messages, **kwargs):
        return {
            "answer": "这是普通聊天回答",
            "model": "general-model",
            "finish_reason": "stop",
        }

    def stream_chat(self, *args, **kwargs):
        raise AssertionError("combined non-streaming chat must not stream")


class FakeSubagent:
    def __init__(self, name):
        self.name = name
        self.invocations = []

    def run(self, invocation):
        self.invocations.append(invocation)
        return {
            "answer": f"{self.name}-answer",
            "agent": self.name,
            "status": "success",
            "finish_reason": "stop",
        }


def make_config() -> AgentConfig:
    return AgentConfig(
        api_key=None,
        base_url="https://example.test/v1",
        model="test-model",
        host="127.0.0.1",
        port=5001,
        request_timeout_seconds=5,
        system_prompt="test",
        web_base_url="https://bbs.example.edu",
    )


class NavigationAgentTest(unittest.TestCase):
    def setUp(self):
        self.agent = NavigationAgent(make_config(), UnusedChatClient())

    def invoke(self, message):
        return self.agent.run(
            AgentInvocation(
                payload={"agent": "navigation", "message": message},
                messages=[{"role": "user", "content": message}],
                options=ChatOptions(),
            )
        )

    def test_routes_learning_materials_to_rag(self):
        result = self.invoke("帮我检索信号与系统的课程资料和讲义")
        self.assertEqual(result["intent"], "knowledge_search")
        self.assertEqual(result["routes"][0]["module"], "knowledge_rag")
        self.assertTrue(result["routes"][0]["url"].startswith("https://bbs.example.edu/knowledge?q="))

    def test_routes_use_prefilled_local_agent_test_pages_without_web_frontend(self):
        config = AgentConfig(**{**make_config().__dict__, "web_base_url": ""})
        agent = NavigationAgent(config, UnusedChatClient())
        message = "帮我检索信号与系统的课程资料和讲义"
        result = agent.run(
            AgentInvocation(
                payload={"agent": "navigation", "message": message},
                messages=[{"role": "user", "content": message}],
                options=ChatOptions(),
            )
        )
        url = result["routes"][0]["url"]
        self.assertTrue(url.startswith("/dev/rag-test?"))
        self.assertIn("agent=rag", url)
        self.assertIn("source=navigation_knowledge_rag", url)
        self.assertIn("message=", url)

    def test_routes_announcements(self):
        result = self.invoke("最近有什么讲座通知，报名什么时候截止？")
        self.assertEqual(result["intent"], "announcement")
        self.assertEqual(result["routes"][0]["module"], "announcements")

    def test_supports_multiple_intents(self):
        result = self.invoke("这道习题不会做，我想找资料再去讨论区请教同学")
        modules = {route["module"] for route in result["routes"]}
        self.assertIn("knowledge_rag", modules)
        self.assertIn("course_discussion", modules)
        self.assertLessEqual(len(result["routes"]), 3)

    def test_ambiguous_input_asks_for_clarification(self):
        result = self.invoke("帮帮我")
        self.assertEqual(result["intent"], "clarify")
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["confidence"], 0.0)

    def test_stream_contains_clickable_markdown(self):
        invocation = AgentInvocation(
            payload={"agent": "navigation", "message": "查看课程通知"},
            messages=[{"role": "user", "content": "查看课程通知"}],
            options=ChatOptions(stream=True),
        )
        output = "".join(self.agent.stream(invocation))
        self.assertIn("[公告与通知]", output)
        self.assertIn("https://bbs.example.edu/workbench", output)

    def test_app_exposes_agent_and_test_page(self):
        app = create_app(make_config(), UnusedChatClient())
        client = app.test_client()
        response = client.post(
            "/api/v1/chat",
            json={"agent": "navigation", "message": "我想找一个项目和队友"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["intent"], "project")

        page = client.get("/dev/navigation-test", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("导引 Agent", page.get_data(as_text=True))
        self.assertIn("messages:history", page.get_data(as_text=True))
        self.assertIn("新会话", page.get_data(as_text=True))

    def test_llm_can_correct_rule_candidates_and_keeps_server_url(self):
        config = AgentConfig(
            **{**make_config().__dict__, "api_key": "test-key"}
        )
        chat_client = FakeNavigationChatClient()
        agent = NavigationAgent(config, chat_client)
        result = agent.run(
            AgentInvocation(
                payload={"agent": "navigation", "message": "我不知道该先补什么"},
                messages=[{"role": "user", "content": "我不知道该先补什么"}],
                options=ChatOptions(),
            )
        )
        self.assertTrue(result["llm_used"])
        self.assertEqual(result["intent"], "course_graph")
        self.assertEqual(result["model"], "fake-guide-model")
        self.assertTrue(result["routes"][0]["url"].startswith("https://bbs.example.edu/course?q="))
        self.assertEqual(chat_client.calls, 1)

    def test_high_confidence_rule_skips_llm(self):
        config = AgentConfig(
            **{**make_config().__dict__, "api_key": "test-key"}
        )
        chat_client = FakeNavigationChatClient()
        agent = NavigationAgent(config, chat_client)
        message = "帮我找课程资料、讲义和知识库"
        result = agent.run(
            AgentInvocation(
                payload={"agent": "navigation", "message": message},
                messages=[{"role": "user", "content": message}],
                options=ChatOptions(),
            )
        )
        self.assertFalse(result["llm_used"])
        self.assertEqual(result["llm_status"], "skipped_high_rule_confidence")
        self.assertEqual(result["intent"], "knowledge_search")
        self.assertEqual(chat_client.calls, 0)

    def test_fallback_routing_uses_previous_user_turns(self):
        result = self.agent.run(
            AgentInvocation(
                payload={"agent": "navigation"},
                messages=[
                    {"role": "user", "content": "我想找信号与系统的课程资料"},
                    {"role": "assistant", "content": "你想进一步了解什么？"},
                    {"role": "user", "content": "我会计算，但是不知道学这个有什么用"},
                ],
                options=ChatOptions(),
            )
        )
        self.assertFalse(result["llm_used"])
        self.assertEqual(result["llm_status"], "skipped_high_rule_confidence")
        self.assertEqual(result["intent"], "knowledge_search")
        self.assertFalse(result["needs_clarification"])

    def test_auto_delegates_knowledge_search_to_rag(self):
        rag = FakeSubagent("rag")
        info = FakeSubagent("info")
        agent = NavigationAgent(make_config(), UnusedChatClient(), rag_agent=rag, info_agent=info)
        message = "帮我检索信号与系统的课程资料和讲义"
        result = agent.run(
            AgentInvocation(
                payload={
                    "agent": "navigation",
                    "message": message,
                    "execute_subagent": "auto",
                },
                messages=[{"role": "user", "content": message}],
                options=ChatOptions(),
            )
        )
        self.assertEqual(result["delegation"]["selected"], "rag")
        self.assertTrue(result["delegation"]["executed"])
        self.assertEqual(result["subagent"]["agent"], "rag")
        self.assertEqual(result["answer"], "rag-answer")
        self.assertEqual(len(rag.invocations), 1)
        self.assertEqual(len(info.invocations), 0)

    def test_auto_delegates_announcements_to_info_with_trusted_context(self):
        rag = FakeSubagent("rag")
        info = FakeSubagent("info")
        agent = NavigationAgent(make_config(), UnusedChatClient(), rag_agent=rag, info_agent=info)
        trusted_context = {"uid": "user_1", "permissions": ["thu_info:read"]}
        message = "查询最近的课程公告和讲座通知"
        result = agent.run(
            AgentInvocation(
                payload={
                    "agent": "navigation",
                    "message": message,
                    "execute_subagent": "auto",
                    "_trusted_context": trusted_context,
                },
                messages=[{"role": "user", "content": message}],
                options=ChatOptions(),
            )
        )
        self.assertEqual(result["delegation"]["selected"], "info")
        self.assertEqual(result["subagent"]["agent"], "info")
        self.assertEqual(info.invocations[0].payload["_trusted_context"], trusted_context)
        self.assertEqual(len(rag.invocations), 0)

    def test_explicit_subagent_and_invalid_mode(self):
        rag = FakeSubagent("rag")
        info = FakeSubagent("info")
        agent = NavigationAgent(make_config(), UnusedChatClient(), rag_agent=rag, info_agent=info)
        message = "最近有什么通知"
        invocation = AgentInvocation(
            payload={"agent": "navigation", "message": message, "execute_subagent": "rag"},
            messages=[{"role": "user", "content": message}],
            options=ChatOptions(),
        )
        self.assertEqual(agent.run(invocation)["delegation"]["selected"], "rag")
        invocation.payload["execute_subagent"] = "bad"
        with self.assertRaises(ValueError):
            agent.run(invocation)

    def test_combined_chat_uses_general_answer_for_ordinary_conversation(self):
        rag = FakeSubagent("rag")
        info = FakeSubagent("info")
        general = FakeSubagent("general_chat")
        agent = NavigationAgent(
            make_config(),
            UnusedChatClient(),
            rag_agent=rag,
            info_agent=info,
            general_agent=general,
        )
        result = agent.run(
            AgentInvocation(
                payload={
                    "agent": "navigation",
                    "message": "你好，今天过得怎么样？",
                    "execute_subagent": "auto",
                    "combine_general_chat": True,
                },
                messages=[{"role": "user", "content": "你好，今天过得怎么样？"}],
                options=ChatOptions(),
            )
        )
        self.assertEqual(result["agent"], "general_chat")
        self.assertEqual(result["answer"], "general_chat-answer")
        self.assertEqual(result["response_mode"], "general_chat")
        self.assertEqual(result["routes"], [])
        self.assertEqual(len(general.invocations), 1)
        self.assertEqual(len(rag.invocations), 0)

    def test_default_mux_exposes_combined_chat_through_http_api(self):
        app = create_app(make_config(), GeneralChatClient())
        response = app.test_client().post(
            "/api/v1/chat",
            json={
                "agent": "navigation",
                "message": "你好，介绍一下你自己",
                "execute_subagent": "auto",
                "combine_general_chat": True,
            },
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["agent"], "general_chat")
        self.assertEqual(response.get_json()["answer"], "这是普通聊天回答")

    def test_combined_chat_uses_rag_answer_without_navigation_route(self):
        rag = FakeSubagent("rag")
        general = FakeSubagent("general_chat")
        agent = NavigationAgent(
            make_config(),
            UnusedChatClient(),
            rag_agent=rag,
            info_agent=FakeSubagent("info"),
            general_agent=general,
        )
        message = "请解释傅里叶变换这个知识点"
        result = agent.run(
            AgentInvocation(
                payload={
                    "agent": "navigation",
                    "message": message,
                    "execute_subagent": "auto",
                    "combine_general_chat": True,
                },
                messages=[{"role": "user", "content": message}],
                options=ChatOptions(),
            )
        )
        self.assertEqual(result["answer"], "rag-answer")
        self.assertEqual(result["response_mode"], "rag")
        self.assertEqual(result["routes"], [])
        self.assertTrue(result["navigation_routes"])
        self.assertEqual(len(rag.invocations), 1)
        self.assertEqual(len(general.invocations), 1)

    def test_combined_chat_recognizes_conceptual_follow_up_as_rag(self):
        rag = FakeSubagent("rag")
        agent = NavigationAgent(
            make_config(),
            UnusedChatClient(),
            rag_agent=rag,
            info_agent=FakeSubagent("info"),
            general_agent=FakeSubagent("general_chat"),
        )
        message = "傅里叶变换有什么用？"
        result = agent.run(
            AgentInvocation(
                payload={
                    "agent": "navigation",
                    "message": message,
                    "execute_subagent": "auto",
                    "combine_general_chat": True,
                },
                messages=[{"role": "user", "content": message}],
                options=ChatOptions(),
            )
        )
        self.assertEqual(result["response_mode"], "rag")
        self.assertEqual(result["answer"], "rag-answer")

    def test_combined_chat_keeps_routes_for_explicit_navigation(self):
        rag = FakeSubagent("rag")
        general = FakeSubagent("general_chat")
        agent = NavigationAgent(
            make_config(),
            UnusedChatClient(),
            rag_agent=rag,
            info_agent=FakeSubagent("info"),
            general_agent=general,
        )
        message = "带我去课程资料页面"
        result = agent.run(
            AgentInvocation(
                payload={
                    "agent": "navigation",
                    "message": message,
                    "execute_subagent": "auto",
                    "combine_general_chat": True,
                },
                messages=[{"role": "user", "content": message}],
                options=ChatOptions(),
            )
        )
        self.assertTrue(result["navigation_requested"])
        self.assertEqual(result["response_mode"], "navigation")
        self.assertEqual(result["answer"], "general_chat-answer")
        self.assertTrue(result["routes"])
        self.assertEqual(result["delegation"]["selected"], "none")
        self.assertEqual(len(rag.invocations), 0)


if __name__ == "__main__":
    unittest.main()
