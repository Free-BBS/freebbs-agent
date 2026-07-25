from __future__ import annotations

import json
from dataclasses import dataclass

from ..agent_utils import AgentInvocation
from ..ai_client import AIClientError


PLANNER_PROMPT = """你是中文课程知识库的检索规划器，只生成检索计划，不回答问题。
结合最近对话把当前问题改写为独立问题，提取实体和关键词，并给出少量互补子查询。
不要添加对话中没有依据的具体事实。只输出 JSON：
{"standalone_query":"...","intent":"...","entities":[],"keywords":[],"subqueries":[]}"""


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    standalone_query: str
    intent: str = "knowledge_lookup"
    entities: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    subqueries: tuple[str, ...] = ()

    @classmethod
    def original(cls, query: str) -> "QueryPlan":
        return cls(original_query=query, standalone_query=query)

    def queries(self, max_subqueries: int) -> list[str]:
        keyword_query = " ".join((*self.entities, *self.keywords))
        candidates = [
            self.original_query,
            self.standalone_query,
            keyword_query,
            *self.subqueries[:max_subqueries],
        ]
        result: list[str] = []
        for query in candidates:
            cleaned = query.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result

    def as_dict(self) -> dict:
        return {
            "original_query": self.original_query,
            "standalone_query": self.standalone_query,
            "intent": self.intent,
            "entities": list(self.entities),
            "keywords": list(self.keywords),
            "subqueries": list(self.subqueries),
        }


class QueryPlanner:
    def __init__(self, config, chat_client):
        self.config = config
        self.chat_client = chat_client

    def plan(self, invocation: AgentInvocation) -> QueryPlan:
        if not self.config.rag_query_augmentation_enabled:
            return QueryPlan.original(invocation.message)
        try:
            result = self.chat_client.chat(
                [
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": self._conversation_text(invocation)},
                ],
                temperature=0,
                max_tokens=300,
            )
            payload = _parse_json_object(result.get("answer", ""))
            standalone = payload.get("standalone_query")
            if not isinstance(standalone, str) or not standalone.strip():
                raise ValueError("missing standalone query")
            return QueryPlan(
                original_query=invocation.message,
                standalone_query=standalone.strip(),
                intent=_string(payload.get("intent")) or "knowledge_lookup",
                entities=_strings(payload.get("entities")),
                keywords=_strings(payload.get("keywords")),
                subqueries=_strings(payload.get("subqueries"))[: self.config.rag_max_subqueries],
            )
        except (AIClientError, TypeError, ValueError, json.JSONDecodeError):
            return QueryPlan.original(invocation.message)

    def _conversation_text(self, invocation: AgentInvocation) -> str:
        messages = [item for item in invocation.messages if item["role"] in {"user", "assistant"}]
        return "\n".join(f'{item["role"]}: {item["content"]}' for item in messages[-6:])


def _parse_json_object(value: str) -> dict:
    text = (value or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def _string(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
