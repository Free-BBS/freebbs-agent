from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .agent_utils import AgentInvocation
from .ai_client import AIClientError
from .rag.paths import resolve_rag_store_paths


ROUTER_PROMPT = """你是 FREE-BBS 的请求路由器，只做分类，不回答问题。
仅当问题需要查询当前已索引的课程资料或课程知识图谱时选择 rag；
讨论、项目、通知等尚未进入当前索引的请求不要选择 rag；
普通闲聊、写作、通用知识解释选择 general_chat。
只输出 JSON：{"agent":"rag|general_chat","confidence":0到1之间的数字}。"""


@dataclass(frozen=True)
class RouteDecision:
    agent: str
    confidence: float
    mode: str = "online"


class OnlineAgentRouter:
    def __init__(self, config, chat_client):
        self.config = config
        self.chat_client = chat_client

    def route(self, invocation: AgentInvocation) -> RouteDecision:
        if not self._rag_available():
            return RouteDecision(agent="general_chat", confidence=1.0, mode="fallback")
        try:
            result = self.chat_client.chat(
                [
                    {"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": self._conversation_text(invocation)},
                ],
                temperature=0,
                max_tokens=80,
            )
            payload = _parse_json_object(result.get("answer", ""))
            agent = payload.get("agent")
            confidence = float(payload.get("confidence", 0))
            if agent not in {"rag", "general_chat"}:
                raise ValueError("unsupported routed agent")
            if confidence < self.config.online_router_confidence_threshold:
                return RouteDecision(agent="general_chat", confidence=confidence, mode="low_confidence")
            return RouteDecision(agent=agent, confidence=confidence)
        except (AIClientError, TypeError, ValueError, json.JSONDecodeError):
            return RouteDecision(agent="general_chat", confidence=0.0, mode="fallback")

    def _rag_available(self) -> bool:
        if not self.config.online_router_enabled or not self.config.rag_enabled:
            return False

        try:
            root_getter = getattr(self.chat_client, "course_materials_root", None)
            course_materials_root = (
                root_getter() if callable(root_getter) else self.config.course_materials_root
            )

            index_path, metadata_path = resolve_rag_store_paths(
                self.config.rag_index_path,
                self.config.rag_metadata_path,
                course_materials_root,
            )

            return Path(index_path).is_file() and Path(metadata_path).is_file()
        except (AIClientError, OSError, RuntimeError, ValueError):
            return False

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
