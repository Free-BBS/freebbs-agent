from __future__ import annotations

import threading
import time

from .agent_utils import AgentInvocation, Any, ChatOptions, FreeBBSAgent, Iterator
from .course_catalog import infer_course
from .rag.embeddings import build_embedding_client
from .rag.faiss_store import FaissVectorStore, RetrievedChunk
from .rag.manifest import active_store_paths
from .rag.paths import resolve_rag_manifest_path, resolve_rag_store_paths
from .rag.query_planner import QueryPlan, QueryPlanner


class RagAgent(FreeBBSAgent):
    name = "rag"

    def __init__(self, config, chat_client):
        super().__init__(config, chat_client)
        self._embedder = None
        self._store = None
        self._store_paths = None
        self._store_version = None
        self._store_descriptor = None
        self._store_descriptor_checked_at = 0.0
        self._store_lock = threading.Lock()
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
        course = infer_course(
            [
                plan.original_query,
                plan.standalone_query,
                *plan.entities,
                *plan.keywords,
                *(hit.text for hit in retrieved),
            ],
            (hit.source for hit in retrieved),
        )
        if course:
            result["course"] = course
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
        store_paths, store_version = self._resolve_store_descriptor()

        with self._store_lock:
            if self._embedder is None:
                self._embedder = build_embedding_client(self.config)
            embedder = self._embedder

            if (
                self._store is None
                or self._store_paths != store_paths
                or self._store_version != store_version
            ):
                try:
                    candidate_store = FaissVectorStore.load(
                        store_paths[0],
                        store_paths[1],
                    )
                except (OSError, RuntimeError, ValueError):
                    if self._store is None:
                        raise
                else:
                    self._store = candidate_store
                    self._store_paths = store_paths
                    self._store_version = store_version
            store = self._store

        ranked_lists = []
        for query in plan.queries(self.config.rag_max_subqueries):
            query_vector = embedder.embed_query(query)
            ranked_lists.append(store.search(query_vector, top_k=self.config.rag_top_k))
        return _reciprocal_rank_fusion(ranked_lists, top_k=self.config.rag_top_k)

    def _resolve_store_paths(self) -> tuple[str, str]:
        root_getter = getattr(self.chat_client, "course_materials_root", None)
        course_materials_root = (
            root_getter() if callable(root_getter) else self.config.course_materials_root
        )

        return resolve_rag_store_paths(
            self.config.rag_index_path,
            self.config.rag_metadata_path,
            course_materials_root,
        )

    def _resolve_store_descriptor(self) -> tuple[tuple[str, str], str]:
        now = time.monotonic()
        if (
            self._store_descriptor is not None
            and now - self._store_descriptor_checked_at
            < self.config.rag_index_reload_interval_seconds
        ):
            return self._store_descriptor

        root_getter = getattr(self.chat_client, "course_materials_root", None)
        course_materials_root = (
            root_getter() if callable(root_getter) else self.config.course_materials_root
        )
        fallback_paths = resolve_rag_store_paths(
            self.config.rag_index_path,
            self.config.rag_metadata_path,
            course_materials_root,
        )
        manifest_path = resolve_rag_manifest_path(
            self.config.rag_index_manifest_path,
            course_materials_root,
        )
        try:
            descriptor = active_store_paths(manifest_path, fallback_paths)
        except (OSError, ValueError):
            if self._store_descriptor is None:
                raise
            descriptor = self._store_descriptor
        self._store_descriptor = descriptor
        self._store_descriptor_checked_at = now
        return descriptor

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
            "status": "disabled",
            "sources": [],
        }


def _reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    chunks: dict[str, RetrievedChunk] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rank_constant + rank)
            chunks[hit.chunk_id] = hit
    ordered = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [
        RetrievedChunk(
            chunk_id=chunks[chunk_id].chunk_id,
            doc_id=chunks[chunk_id].doc_id,
            source=chunks[chunk_id].source,
            text=chunks[chunk_id].text,
            score=scores[chunk_id],
        )
        for chunk_id in ordered
    ]
