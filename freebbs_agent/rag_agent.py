from __future__ import annotations

from .agent_utils import AgentInvocation, Any, ChatOptions, FreeBBSAgent, Iterator
from .rag.embeddings import build_embedding_client
from .rag.faiss_store import FaissVectorStore, RetrievedChunk
from .rag.fusion import reciprocal_rank_fusion
from .rag.query_planner import QueryPlan, QueryPlanner


class RagAgent(FreeBBSAgent):
    name = "rag"

    def __init__(self, config, chat_client):
        super().__init__(config, chat_client)
        self._embedder = None
        self._store = None
        self._planner = QueryPlanner(config, chat_client)

    def can_handle(self, invocation: AgentInvocation) -> bool:
        requested_agent = invocation.payload.get("agent")
        return requested_agent in {self.name, "rag_agent"}

    def run(self, invocation: AgentInvocation) -> dict[str, Any]:
        if not self.config.rag_enabled:
            return self._disabled_response(invocation.options)

        plan = self._planner.plan(invocation)
        retrieved = self._retrieve(plan)
        messages = self._with_retrieved_context(invocation.messages, retrieved)
        result = self.call_llm(messages, invocation.options)
        result["agent"] = self.name
        result["query_plan"] = plan.as_dict()
        result["sources"] = [
            {
                "chunk_id": hit.chunk_id,
                "doc_id": hit.doc_id,
                "source": hit.source,
                "score": hit.score,
            }
            for hit in retrieved
        ]
        return result

    def stream(self, invocation: AgentInvocation) -> Iterator[str]:
        if not self.config.rag_enabled:
            yield self._disabled_response(invocation.options)["answer"]
            return

        plan = self._planner.plan(invocation)
        retrieved = self._retrieve(plan)
        messages = self._with_retrieved_context(invocation.messages, retrieved)
        yield from self.stream_llm(messages, invocation.options)

    def _retrieve(self, plan: QueryPlan) -> list[RetrievedChunk]:
        if self._embedder is None:
            self._embedder = build_embedding_client(self.config)
        if self._store is None:
            self._store = FaissVectorStore.load(
                self.config.rag_index_path,
                self.config.rag_metadata_path,
            )
        ranked_lists = []
        weights = []
        for query in plan.queries(self.config.rag_max_subqueries):
            query_vector = self._embedder.embed_query(query)
            ranked_lists.append(self._store.search(query_vector, top_k=self.config.rag_top_k))
            weights.append(1.0)
            ranked_lists.append(self._store.search_keywords(query, top_k=self.config.rag_top_k))
            weights.append(0.5)
        return reciprocal_rank_fusion(
            ranked_lists,
            top_k=self.config.rag_top_k,
            weights=weights,
        )

    def _with_retrieved_context(
        self,
        messages: list[dict[str, str]],
        retrieved: list[RetrievedChunk],
    ) -> list[dict[str, str]]:
        if not retrieved:
            return messages
        lines = []
        for index, hit in enumerate(retrieved[: self.config.rag_max_context_chunks], start=1):
            lines.append(f"[{index}] source={hit.source} score={hit.score:.4f}\n{hit.text}")
        rag_context = (
            "以下是检索到的候选资料片段。请优先基于这些资料回答，并在不确定时明确说明：\n\n"
            + "\n\n".join(lines)
        )
        adjusted = [message.copy() for message in messages]
        for message in adjusted:
            if message["role"] == "system":
                message["content"] = f"{message['content']}\n\n{rag_context}"
                return adjusted
        return [{"role": "system", "content": f"{self.config.system_prompt}\n\n{rag_context}"}] + adjusted

    def _disabled_response(self, options: ChatOptions) -> dict[str, Any]:
        return {
            "answer": "RAG agent is disabled. Set RAG_ENABLED=true and build index first.",
            "model": options.model or self.config.model,
            "finish_reason": "stop",
            "agent": self.name,
            "sources": [],
        }
