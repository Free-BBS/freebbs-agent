from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import quote_plus

from .agent_utils import AgentInvocation, Any, FreeBBSAgent, Iterator
from .ai_client import AIClientError


@dataclass(frozen=True)
class NavigationTarget:
    intent: str
    module: str
    title: str
    path: str
    test_path: str
    test_agent: str
    test_source: str
    description: str
    keywords: tuple[tuple[str, int], ...]


TARGETS = (
    NavigationTarget(
        intent="knowledge_search",
        module="knowledge_rag",
        title="知识 RAG Agent",
        path="/knowledge",
        test_path="/dev/rag-test",
        test_agent="rag",
        test_source="navigation_knowledge_rag",
        description="检索课程资料、讲义、知识点解释与学习资源。",
        keywords=(
            ("资料", 4), ("讲义", 4), ("课件", 4), ("知识库", 4), ("rag", 5),
            ("搜索", 2), ("检索", 3), ("查找", 2), ("概念", 2), ("解释", 2),
            ("是什么", 2), ("怎么理解", 3), ("公式", 2), ("习题", 2),
        ),
    ),
    NavigationTarget(
        intent="announcement",
        module="announcements",
        title="公告与通知",
        path="/workbench",
        test_path="/dev/info-test",
        test_agent="info",
        test_source="navigation_announcements",
        description="查看课程、考试、作业、讲座、活动和项目通知。",
        keywords=(
            ("公告", 5), ("通知", 5), ("截止", 4), ("ddl", 4), ("deadline", 4),
            ("考试时间", 5), ("作业要求", 4), ("讲座", 4), ("活动", 3),
            ("报名", 3), ("什么时候", 2), ("安排", 2),
        ),
    ),
    NavigationTarget(
        intent="course_discussion",
        module="course_discussion",
        title="课程讨论区",
        path="/discussion",
        test_path="/dev/comment-test",
        test_agent="comment",
        test_source="navigation_course_discussion",
        description="提问、交流解题思路、寻找同学或参与课程讨论。",
        keywords=(
            ("讨论", 5), ("讨论区", 6), ("发帖", 5), ("帖子", 4), ("求助", 3),
            ("同学", 2), ("交流", 3), ("怎么看", 2), ("请教", 3),
            ("卡住", 2), ("不会做", 3), ("答疑", 4),
        ),
    ),
    NavigationTarget(
        intent="course_graph",
        module="course_graph",
        title="课程与知识图谱",
        path="/course",
        test_path="/dev/course-graph-test",
        test_agent="general",
        test_source="navigation_course_graph",
        description="查看课程关系、先修知识和推荐学习路径。",
        keywords=(
            ("课程", 3), ("选课", 5), ("先修", 5), ("培养方案", 5), ("知识图谱", 5),
            ("学习路径", 4), ("怎么学", 3), ("规划", 3), ("前置知识", 4),
        ),
    ),
    NavigationTarget(
        intent="project",
        module="pbl",
        title="PBL 项目孵化器",
        path="/development",
        test_path="/dev/project-test",
        test_agent="general",
        test_source="navigation_pbl",
        description="寻找实践项目、项目队友和工程探索机会。",
        keywords=(
            ("项目", 4), ("pbl", 5), ("队友", 5), ("组队", 5), ("实践", 3),
            ("开发", 2), ("比赛", 3), ("竞赛", 3), ("选题", 3), ("作品", 2),
        ),
    ),
    NavigationTarget(
        intent="learning_profile",
        module="learning_profile",
        title="个性化学习印记",
        path="/profile",
        test_path="/dev/learning-profile-test",
        test_agent="general",
        test_source="navigation_learning_profile",
        description="回顾学习轨迹、能力画像与个人学习状态。",
        keywords=(
            ("学习状态", 5), ("学习记录", 5), ("学习轨迹", 5), ("能力画像", 5),
            ("我的进度", 4), ("复盘", 4), ("反思", 3), ("薄弱", 3),
        ),
    ),
)


EXPLICIT_NAVIGATION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:带我|领我)(?:去|到)",
        r"(?:打开|进入|跳转到?|导航到?|前往)(?:一下|这个|那个|对应的)?(?:页面|模块|功能|入口|知识地图|讨论区|工作台)?",
        r"(?:页面|模块|功能|入口|知识地图|讨论区|工作台)(?:在)?哪(?:里|儿)",
        r"怎么(?:去|进入|打开|找到)(?:页面|模块|功能|入口|知识地图|讨论区|工作台)?",
        r"(?:我想|我要|我需要)?去(?:一下)?(?:知识地图|讨论区|工作台|项目区|个人主页)",
        r"(?:找|寻找).*(?:项目|队友|组队|讨论区|学习记录|能力画像)",
    )
)

KNOWLEDGE_QUESTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"什么是.{2,}",
        r".{2,}是什么",
        r"(?:解释|推导|证明|分析).{2,}",
        r".{2,}(?:知识点|原理|公式|定理|定律)",
        r".{2,}(?:有什么用|有何作用|怎么理解|如何理解|怎么算|如何计算)",
    )
)


class NavigationAgent(FreeBBSAgent):
    """Use an LLM to guide users, with deterministic routing as a safe fallback."""

    name = "navigation"
    aliases = {"guide", "navigator", "intent_router"}
    max_routes = 3

    def __init__(
        self,
        config,
        chat_client,
        *,
        rag_agent: FreeBBSAgent | None = None,
        info_agent: FreeBBSAgent | None = None,
        general_agent: FreeBBSAgent | None = None,
    ) -> None:
        super().__init__(config, chat_client)
        self.rag_agent = rag_agent
        self.info_agent = info_agent
        self.general_agent = general_agent

    def can_handle(self, invocation: AgentInvocation) -> bool:
        requested_agent = invocation.payload.get("agent")
        return requested_agent == self.name or requested_agent in self.aliases

    def run(self, invocation: AgentInvocation) -> dict[str, Any]:
        if invocation.payload.get("combine_general_chat") and self.general_agent is not None:
            return self._run_combined_chat(invocation)
        navigation_result = self._navigate(invocation)
        return self._delegate(invocation, navigation_result)

    def _run_combined_chat(self, invocation: AgentInvocation) -> dict[str, Any]:
        """Run normal chat and navigation together, then select the useful surface."""

        general_invocation = self._general_invocation(invocation)
        with ThreadPoolExecutor(max_workers=2) as executor:
            navigation_future = executor.submit(self._navigate, invocation)
            general_future = executor.submit(self.general_agent.run, general_invocation)
            navigation_result = navigation_future.result()
            try:
                general_result = general_future.result()
            except (AIClientError, ValueError, TypeError):
                general_result = None

        navigation_requested = self._is_explicit_navigation(invocation.message)
        result = self._delegate(
            invocation,
            navigation_result,
            navigation_requested=navigation_requested,
        )
        result["navigation_requested"] = navigation_requested

        selected = result.get("delegation", {}).get("selected")
        if (
            selected == "rag"
            and result.get("delegation", {}).get("executed")
            and result.get("subagent", {}).get("status") != "disabled"
        ):
            result["navigation_routes"] = result.get("routes", [])
            result["routes"] = []
            result["response_mode"] = "rag"
            return result

        if selected == "info" and result.get("delegation", {}).get("executed"):
            result["response_mode"] = "info"
            return result

        if navigation_requested and not navigation_result.get("needs_clarification"):
            result["response_mode"] = "navigation"
            if general_result and general_result.get("answer"):
                result["navigation_answer"] = navigation_result["answer"]
                result["chat_answer"] = general_result["answer"]
                result["answer"] = general_result["answer"]
            return result

        if general_result and general_result.get("answer"):
            navigation_snapshot = {
                key: result.get(key)
                for key in (
                    "intent",
                    "confidence",
                    "needs_clarification",
                    "routes",
                    "llm_used",
                    "llm_status",
                )
            }
            result.update(
                {
                    "answer": general_result["answer"],
                    "agent": "general_chat",
                    "intent": "general_chat",
                    "routes": [],
                    "model": general_result.get("model", self.config.model),
                    "finish_reason": general_result.get("finish_reason", "stop"),
                    "response_mode": "general_chat",
                    "navigation": navigation_snapshot,
                }
            )
        return result

    @staticmethod
    def _general_invocation(invocation: AgentInvocation) -> AgentInvocation:
        payload = dict(invocation.payload)
        payload["agent"] = "general_chat"
        payload.pop("execute_subagent", None)
        payload.pop("combine_general_chat", None)
        return AgentInvocation(
            payload=payload,
            messages=invocation.messages,
            options=invocation.options,
        )

    @staticmethod
    def _is_explicit_navigation(message: str) -> bool:
        normalized = message.casefold().strip()
        return any(pattern.search(normalized) for pattern in EXPLICIT_NAVIGATION_PATTERNS)

    def _navigate(self, invocation: AgentInvocation) -> dict[str, Any]:
        routing_query = self._routing_query(invocation)
        ranked = self._rank_targets(routing_query)
        rule_confidence = self._rule_confidence(ranked)

        if rule_confidence >= self.config.navigation_llm_confidence_threshold:
            return self._deterministic_result(
                ranked,
                invocation.message,
                llm_status="skipped_high_rule_confidence",
            )

        if self.config.navigation_llm_enabled and self.config.api_key:
            try:
                return self._run_with_llm(invocation, ranked)
            except (AIClientError, ValueError, TypeError, json.JSONDecodeError):
                # Navigation must remain usable when the provider is unavailable or
                # returns malformed structured output.
                return self._deterministic_result(
                    ranked,
                    invocation.message,
                    llm_status="provider_error_or_invalid_response",
                )

        status = "disabled" if not self.config.navigation_llm_enabled else "missing_api_key"
        return self._deterministic_result(ranked, invocation.message, llm_status=status)

    def _delegate(
        self,
        invocation: AgentInvocation,
        navigation_result: dict[str, Any],
        *,
        navigation_requested: bool = False,
    ) -> dict[str, Any]:
        """Optionally execute one routed sub-agent and retain the navigation result."""

        requested = invocation.payload.get("execute_subagent", "none")
        if requested is True:
            requested = "auto"
        elif requested is False or requested is None:
            requested = "none"
        if requested not in {"none", "auto", "rag", "info"}:
            raise ValueError("execute_subagent must be one of: none, auto, rag, info")

        selected = requested
        if selected == "auto":
            selected = (
                "none"
                if navigation_requested
                else {
                    "knowledge_search": "rag",
                    "announcement": "info",
                }.get(navigation_result.get("intent"), "none")
            )

        if navigation_result.get("needs_clarification"):
            selected = "none"

        subagent = {"rag": self.rag_agent, "info": self.info_agent}.get(selected)
        result = dict(navigation_result)
        result["delegation"] = {
            "requested": requested,
            "selected": selected,
            "executed": subagent is not None,
        }
        if subagent is None:
            return result

        child_payload = dict(invocation.payload)
        child_payload["agent"] = selected
        child_payload["stream"] = False
        child_payload["delegated_by"] = self.name
        child_invocation = AgentInvocation(
            payload=child_payload,
            messages=invocation.messages,
            options=invocation.options,
        )
        child_result = subagent.run(child_invocation)
        result["navigation_answer"] = navigation_result["answer"]
        result["answer"] = child_result.get("answer", navigation_result["answer"])
        result["subagent"] = child_result
        result["delegation"]["status"] = child_result.get("status", "completed")
        return result

    @staticmethod
    def _rule_confidence(ranked: list[tuple[int, NavigationTarget]]) -> float:
        top_score = ranked[0][0] if ranked else 0
        return min(0.99, top_score / (top_score + 3)) if top_score else 0.0

    def _deterministic_result(
        self,
        ranked: list[tuple[int, NavigationTarget]],
        query: str,
        *,
        llm_status: str,
    ) -> dict[str, Any]:
        routes = self._select_routes(ranked, query)
        top_score = ranked[0][0] if ranked else 0
        confidence = round(self._rule_confidence(ranked), 2)
        needs_clarification = top_score < 3

        if needs_clarification:
            answer = (
                "我还不能确定你想去哪个模块。你是在找课程资料、查看公告通知，"
                "还是想进入课程讨论区？也可以直接说“找项目”或“查看学习记录”。"
            )
        else:
            names = "、".join(route["title"] for route in routes)
            answer = f"我判断你的需求适合前往：{names}。点击下面的入口即可继续。"

        return {
            "answer": answer,
            "agent": self.name,
            "intent": routes[0]["intent"] if routes and not needs_clarification else "clarify",
            "confidence": confidence,
            "needs_clarification": needs_clarification,
            "routes": routes,
            "model": "deterministic-intent-router-v1",
            "llm_used": False,
            "llm_status": llm_status,
            "finish_reason": "stop",
        }

    def _run_with_llm(
        self,
        invocation: AgentInvocation,
        ranked: list[tuple[int, NavigationTarget]],
    ) -> dict[str, Any]:
        candidates = self._select_routes(ranked, invocation.message)
        catalog = "\n".join(
            f"- {target.intent}: {target.title}；{target.description}"
            for target in TARGETS
        )
        candidate_names = "、".join(route["intent"] for route in candidates) or "无"
        system_prompt = f"""你是 FREE-BBS 的导引员。理解用户真正想完成的学习任务，
用简洁、友好、具体的中文给出下一步。只能从下面的入口中选择 1 到 3 个 intent：
{catalog}

规则：
1. 结合完整对话理解省略、指代和用户当前阶段，不只做关键词匹配。
2. 信息足够时给出直接、可执行的引导；信息不足时提出最多 3 个有区分度的短问题。
3. 不编造平台功能、课程规定或 URL，不替用户完成应独立完成的作业。
4. 规则召回候选仅供参考：{candidate_names}，你可以纠正它。
5. 只输出 JSON 对象，不要 Markdown。格式：
{{"intents":["intent"],"answer":"引导语","needs_clarification":false,
"confidence":0.0,"reason_by_intent":{{"intent":"贴合用户需求的推荐理由"}}}}
confidence 必须是 0 到 1。模糊请求可返回最多 3 个最可能入口，并设 needs_clarification=true。"""
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(message for message in invocation.messages if message["role"] != "system")
        llm_result = self.chat_client.chat(
            messages,
            model=self.config.navigation_model or invocation.options.model,
            temperature=0.2 if invocation.options.temperature is None else invocation.options.temperature,
            max_tokens=700 if invocation.options.max_tokens is None else invocation.options.max_tokens,
        )
        decision = self._parse_llm_json(llm_result.get("answer"))
        intents = decision.get("intents")
        if not isinstance(intents, list):
            raise ValueError("navigation LLM did not return intents")

        targets_by_intent = {target.intent: target for target in TARGETS}
        selected_targets = []
        for intent in intents:
            if intent in targets_by_intent and intent not in [item.intent for item in selected_targets]:
                selected_targets.append(targets_by_intent[intent])
            if len(selected_targets) == self.max_routes:
                break
        if not selected_targets:
            raise ValueError("navigation LLM returned no valid intent")

        reasons = decision.get("reason_by_intent")
        reasons = reasons if isinstance(reasons, dict) else {}
        score_by_intent = {target.intent: score for score, target in ranked}
        routes = [
            {
                "intent": target.intent,
                "module": target.module,
                "title": target.title,
                "url": self._target_url(target, invocation.message),
                "reason": reasons.get(target.intent) or target.description,
                "score": score_by_intent.get(target.intent, 0),
            }
            for target in selected_targets
        ]
        needs_clarification = bool(decision.get("needs_clarification", False))
        confidence = decision.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        answer = decision.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("navigation LLM did not return an answer")

        return {
            "answer": answer.strip(),
            "agent": self.name,
            "intent": "clarify" if needs_clarification else routes[0]["intent"],
            "confidence": round(max(0.0, min(1.0, float(confidence))), 2),
            "needs_clarification": needs_clarification,
            "routes": routes,
            "model": llm_result.get("model", self.config.navigation_model or self.config.model),
            "llm_used": True,
            "llm_status": "used",
            "finish_reason": llm_result.get("finish_reason", "stop"),
        }

    @staticmethod
    def _routing_query(invocation: AgentInvocation) -> str:
        """Keep deterministic fallback aware of the current conversation.

        Earlier user turns retain the established topic while the latest turn can
        refine it. Repeating the latest turn gives it slightly more routing weight.
        """

        user_turns = [
            message["content"]
            for message in invocation.messages
            if message["role"] == "user"
        ]
        if not user_turns:
            return invocation.message
        return "\n".join([*user_turns, user_turns[-1]])

    @staticmethod
    def _parse_llm_json(content: Any) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ValueError("navigation LLM returned empty content")
        text = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1)
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("navigation LLM response must be an object")
        return parsed

    def stream(self, invocation: AgentInvocation) -> Iterator[str]:
        result = self.run(invocation)
        lines = [result["answer"]]
        lines.extend(f"- [{route['title']}]({route['url']})：{route['reason']}" for route in result["routes"])
        yield "\n".join(lines)

    def _rank_targets(self, message: str) -> list[tuple[int, NavigationTarget]]:
        normalized = message.casefold().strip()
        ranked = []
        for target in TARGETS:
            score = sum(weight for keyword, weight in target.keywords if keyword in normalized)
            if target.intent == "knowledge_search" and any(
                pattern.search(normalized) for pattern in KNOWLEDGE_QUESTION_PATTERNS
            ):
                score += 3
            ranked.append((score, target))
        return sorted(ranked, key=lambda item: item[0], reverse=True)

    def _select_routes(
        self,
        ranked: list[tuple[int, NavigationTarget]],
        query: str,
    ) -> list[dict[str, Any]]:
        if not ranked:
            return []

        top_score = ranked[0][0]
        if top_score < 3:
            selected = ranked[:3]
        else:
            # Keep every independently strong intent instead of suppressing a valid
            # secondary request merely because another intent has more trigger words.
            selected = [item for item in ranked if item[0] >= 3][: self.max_routes]

        return [
            {
                "intent": target.intent,
                "module": target.module,
                "title": target.title,
                "url": self._target_url(target, query),
                "reason": target.description,
                "score": score,
            }
            for score, target in selected
        ]

    def _target_url(self, target: NavigationTarget, query: str) -> str:
        base_url = self.config.web_base_url.rstrip("/")
        if base_url:
            return f"{base_url}{target.path}?q={quote_plus(query)}"

        # In standalone development there is no FREE-BBS web application serving
        # the production module paths. Route cards to the local visual test bench
        # and preselect the corresponding agent/scenario instead of opening a 404.
        return (
            f"{target.test_path}"
            f"?agent={quote_plus(target.test_agent)}"
            f"&source={quote_plus(target.test_source)}"
            f"&message={quote_plus(query)}"
        )
