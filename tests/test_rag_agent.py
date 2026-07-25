import tempfile
import unittest
from pathlib import Path

from freebbs_agent.app import create_app
from freebbs_agent.config import AgentConfig
from freebbs_agent.rag.embeddings import LocalEmbeddingClient, build_embedding_client
from freebbs_agent.rag.faiss_store import FaissVectorStore
from freebbs_agent.rag_agent import RagAgent
from freebbs_agent.agent_utils import AgentInvocation, ChatOptions


class FakeChatClient:
    def __init__(self):
        self.calls = []

    def chat(self, messages, *, model=None, temperature=None, max_tokens=None):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return {"answer": "rag-answer", "model": model or "test-model", "finish_reason": "stop"}

    def stream_chat(self, messages, *, model=None, temperature=None, max_tokens=None):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
        )
        yield "片"
        yield "段"


def make_config(index_path: str, metadata_path: str, *, rag_enabled: bool = True) -> AgentConfig:
    return AgentConfig(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        host="127.0.0.1",
        port=5001,
        request_timeout_seconds=5,
        system_prompt="Default test prompt.",
        rag_enabled=rag_enabled,
        rag_index_path=index_path,
        rag_metadata_path=metadata_path,
        rag_top_k=2,
        rag_max_context_chunks=2,
        rag_embedding_provider="local",
        rag_local_embedding_model="test-local-model",
        rag_local_embedding_dim=16,
        rag_local_model_dir=None,
        rag_local_files_only=True,
        rag_hf_endpoint="https://hf-mirror.com",
    )


def build_index(index_path: str, metadata_path: str):
    embedder = LocalEmbeddingClient(
        model_name="test-local-model",
        output_dim=16,
        local_files_only=True,
        hf_endpoint="https://hf-mirror.com",
    )
    metadata = [
        {
            "chunk_id": "doc1#0",
            "doc_id": "doc1",
            "source": "intro.md",
            "text": "傅里叶变换用于把时域信号转换到频域。",
        },
        {
            "chunk_id": "doc2#0",
            "doc_id": "doc2",
            "source": "network.md",
            "text": "网络通信强调分层协议和数据包传输。",
        },
    ]
    vectors = embedder.embed_documents([row["text"] for row in metadata])
    store = FaissVectorStore.build(vectors, metadata)
    store.save(index_path, metadata_path)


class RagAgentTest(unittest.TestCase):
    def setUp(self):
        try:
            import faiss  # noqa: F401
        except ImportError:
            self.skipTest("faiss-cpu is required for rag tests")

    def test_build_embedding_client_local(self):
        config = make_config("index.faiss", "meta.jsonl")
        client = build_embedding_client(config)
        vector = client.embed_query("测试 query")
        self.assertEqual(len(vector), 16)

    def test_build_embedding_client_api_requires_key(self):
        config = make_config("index.faiss", "meta.jsonl")
        config = AgentConfig(
            api_key=None,
            base_url=config.base_url,
            model=config.model,
            host=config.host,
            port=config.port,
            request_timeout_seconds=config.request_timeout_seconds,
            system_prompt=config.system_prompt,
            rag_enabled=config.rag_enabled,
            rag_index_path=config.rag_index_path,
            rag_metadata_path=config.rag_metadata_path,
            rag_top_k=config.rag_top_k,
            rag_max_context_chunks=config.rag_max_context_chunks,
            rag_embedding_provider="api",
            rag_local_embedding_model=config.rag_local_embedding_model,
            rag_local_embedding_dim=config.rag_local_embedding_dim,
            rag_local_model_dir=config.rag_local_model_dir,
            rag_local_files_only=config.rag_local_files_only,
            rag_hf_endpoint=config.rag_hf_endpoint,
            rag_embedding_api_key=None,
            rag_embedding_base_url=config.rag_embedding_base_url,
            rag_embedding_model=config.rag_embedding_model,
        )
        with self.assertRaises(ValueError):
            build_embedding_client(config)

    def test_rag_agent_run_with_retrieval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = str(Path(temp_dir) / "index.faiss")
            metadata_path = str(Path(temp_dir) / "metadata.jsonl")
            build_index(index_path, metadata_path)

            config = make_config(index_path, metadata_path)
            chat_client = FakeChatClient()
            agent = RagAgent(config, chat_client)
            invocation = AgentInvocation(
                payload={"agent": "rag", "message": "解释频域分析"},
                messages=[{"role": "user", "content": "解释频域分析"}],
                options=ChatOptions(),
            )

            result = agent.run(invocation)
            self.assertEqual(result["agent"], "rag")
            self.assertTrue(result["sources"])
            self.assertEqual(result["answer"], "rag-answer")
            self.assertEqual(result["query_plan"]["standalone_query"], "解释频域分析")
            self.assertEqual(len(chat_client.calls), 2)

    def test_query_augmentation_uses_multiple_queries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = str(Path(temp_dir) / "index.faiss")
            metadata_path = str(Path(temp_dir) / "metadata.jsonl")
            build_index(index_path, metadata_path)
            config = make_config(index_path, metadata_path)

            class PlannerChatClient(FakeChatClient):
                def chat(self, messages, *, model=None, temperature=None, max_tokens=None):
                    self.calls.append({"messages": messages})
                    if "检索规划器" in messages[0]["content"]:
                        return {
                            "answer": (
                                '{"standalone_query":"傅里叶变换的频域用途",'
                                '"intent":"concept","entities":["傅里叶变换"],'
                                '"keywords":["频域"],"subqueries":["时域转换到频域","频域分析"]}'
                            ),
                            "model": "test-model",
                            "finish_reason": "stop",
                        }
                    return {"answer": "rag-answer", "model": "test-model", "finish_reason": "stop"}

            chat_client = PlannerChatClient()
            agent = RagAgent(config, chat_client)
            invocation = AgentInvocation(
                payload={"agent": "rag", "message": "它有什么用？"},
                messages=[
                    {"role": "user", "content": "什么是傅里叶变换？"},
                    {"role": "assistant", "content": "它连接时域和频域。"},
                    {"role": "user", "content": "它有什么用？"},
                ],
                options=ChatOptions(),
            )
            result = agent.run(invocation)
            self.assertEqual(result["query_plan"]["standalone_query"], "傅里叶变换的频域用途")
            self.assertEqual(len(result["query_plan"]["subqueries"]), 2)
            self.assertTrue(result["sources"])

    def test_app_automatically_routes_course_question_to_rag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = str(Path(temp_dir) / "index.faiss")
            metadata_path = str(Path(temp_dir) / "metadata.jsonl")
            build_index(index_path, metadata_path)
            config = make_config(index_path, metadata_path)

            class RoutingChatClient(FakeChatClient):
                def chat(self, messages, *, model=None, temperature=None, max_tokens=None):
                    self.calls.append({"messages": messages})
                    prompt = messages[0]["content"]
                    if "请求路由器" in prompt:
                        return {"answer": '{"agent":"rag","confidence":0.95}', "model": "test-model"}
                    if "检索规划器" in prompt:
                        return {
                            "answer": '{"standalone_query":"傅里叶变换课程知识","subqueries":[]}',
                            "model": "test-model",
                        }
                    return {"answer": "rag-answer", "model": "test-model", "finish_reason": "stop"}

            app = create_app(config, RoutingChatClient())
            response = app.test_client().post(
                "/api/v1/chat",
                json={"message": "课程资料里如何解释傅里叶变换？"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["agent"], "rag")

    def test_rag_agent_disabled_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(
                str(Path(temp_dir) / "index.faiss"),
                str(Path(temp_dir) / "metadata.jsonl"),
                rag_enabled=False,
            )
            chat_client = FakeChatClient()
            agent = RagAgent(config, chat_client)
            invocation = AgentInvocation(
                payload={"agent": "rag", "message": "解释频域分析"},
                messages=[{"role": "user", "content": "解释频域分析"}],
                options=ChatOptions(),
            )
            result = agent.run(invocation)
            self.assertIn("disabled", result["answer"].lower())
            self.assertEqual(result["sources"], [])
            self.assertEqual(len(chat_client.calls), 0)

    def test_app_routes_rag_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = str(Path(temp_dir) / "index.faiss")
            metadata_path = str(Path(temp_dir) / "metadata.jsonl")
            build_index(index_path, metadata_path)

            config = make_config(index_path, metadata_path)
            chat_client = FakeChatClient()
            app = create_app(config, chat_client)
            client = app.test_client()
            response = client.post(
                "/api/v1/chat",
                json={"agent": "rag", "message": "傅里叶变换有什么用？"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["agent"], "rag")


if __name__ == "__main__":
    unittest.main()
