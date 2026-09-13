import unittest
from types import SimpleNamespace
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from freebbs_agent.ai_client import AIClientError, ChatClient
from freebbs_agent.reasoning_stream import current_progress, ModelProgress, reasoning_events
from test_ai_client import make_config


def chunk(content=None, reasoning=None, finish=None):
    return SimpleNamespace(model="test-model", choices=[SimpleNamespace(
        delta=SimpleNamespace(content=content, reasoning_content=reasoning), finish_reason=finish)])


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
    def __iter__(self):
        return iter(self.chunks)
    def close(self):
        self.closed = True


class ReasoningStreamTests(unittest.TestCase):
    def test_glm52_progress_stream_uses_high_effort_and_keeps_reasoning_events(self):
        stream = Stream([chunk(reasoning="计算分压"), chunk(content="2.5 V"), chunk(finish="stop")])
        requests = []
        def create(**payload):
            requests.append(payload)
            return stream
        client = ChatClient(make_config(model="glm-5.2"), client_factory=lambda **kwargs:
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        events = []
        token = current_progress.set(ModelProgress(events.append, Event(), answers=True))
        try:
            result = client.chat([{"role": "user", "content": "计算分压"}])
        finally:
            current_progress.reset(token)
        self.assertEqual(requests[0]["extra_body"], {
            "thinking": {"type": "enabled"}, "reasoning_effort": "high"})
        self.assertTrue(requests[0]["stream"])
        self.assertEqual(result["answer"], "2.5 V")
        self.assertEqual(events[0]["reasoning_delta"], "计算分压")
        self.assertTrue(stream.closed)

    def client(self, chunks):
        self.stream = Stream(chunks)
        completions = SimpleNamespace(create=lambda **payload: self.stream)
        return ChatClient(make_config(), client_factory=lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=completions)))

    def test_reasoning_is_emitted_before_answer_and_never_enters_final_content(self):
        client = self.client([chunk(reasoning="先分析<script>"), chunk(content="答案"), chunk(finish="stop")])
        events = []
        progress = ModelProgress(events.append, Event(), answers=True)
        token = current_progress.set(progress)
        try:
            result = client.chat([{"role": "user", "content": "测试"}])
        finally:
            current_progress.reset(token)
        self.assertEqual(result, {"answer": "答案", "model": "test-model", "finish_reason": "stop"})
        self.assertEqual(events, [{"reasoning_delta": "先分析<script>", "reasoning_id": "1"}, {"delta": "答案"}])
        self.assertTrue(self.stream.closed)
        self.assertIsNone(current_progress.get())

    def test_parallel_navigation_preserves_metadata_without_streaming_internal_json(self):
        client = self.client([chunk(reasoning="规划"), chunk(content="内部JSON"), chunk(finish="stop")])
        class Agent:
            name = "navigation"
            def run(self, invocation):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    answer = pool.submit(copy_context().run, client.chat, [{"role": "user", "content": "测试"}]).result()
                return {**answer, "routes": [{"url": "/world"}], "subagent": {"agent": "rag"}}
        events = list(reasoning_events(Agent(), None))
        self.assertTrue(any(event and event.get("reasoning_delta") == "规划" for event in events))
        self.assertFalse(any(event and "delta" in event for event in events))
        self.assertEqual(events[-1]["result"]["routes"], [{"url": "/world"}])
        self.assertEqual(events[-1]["result"]["subagent"], {"agent": "rag"})
        self.assertTrue(events[-1]["done"])

    def test_truncated_stream_fails_and_closes_provider(self):
        client = self.client([chunk(reasoning="尚未完成")])
        token = current_progress.set(ModelProgress(lambda event: None, Event()))
        try:
            with self.assertRaises(AIClientError):
                client.chat([{"role": "user", "content": "测试"}])
        finally:
            current_progress.reset(token)
        self.assertTrue(self.stream.closed)

    def test_progress_cancellation_closes_active_provider(self):
        stream = Stream([])
        progress = ModelProgress(lambda event: None, Event())
        with progress.track(stream):
            progress.close()
            self.assertTrue(stream.closed)
            self.assertTrue(progress.cancelled.is_set())

    def test_thread_local_callbacks_do_not_mix_users(self):
        def run(label):
            events = []
            token = current_progress.set(ModelProgress(events.append, Event()))
            try:
                current_progress.get().send("1", reasoning=label)
                return events
            finally:
                current_progress.reset(token)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(run, ["用户A", "用户B"]))
        self.assertEqual(first[0]["reasoning_delta"], "用户A")
        self.assertEqual(second[0]["reasoning_delta"], "用户B")
