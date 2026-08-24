from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CourseDefinition:
    slug: str
    name: str
    board: str
    aliases: tuple[str, ...]
    topics: tuple[str, ...]


COURSES = (
    CourseDefinition(
        slug="math",
        name="数理基础",
        board="math",
        aliases=(
            "数理基础",
            "数理",
            "mathematical foundations",
            "高等数学",
            "高数",
            "微积分",
            "线性代数",
            "概率统计",
            "概率论",
        ),
        topics=("导数", "积分", "矩阵", "特征值", "复指数", "随机变量", "概率分布"),
    ),
    CourseDefinition(
        slug="signals",
        name="信号系统",
        board="signal",
        aliases=("信号与系统", "信号系统", "signals and systems"),
        topics=(
            "傅里叶",
            "fourier",
            "频域",
            "时域",
            "卷积",
            "冲激响应",
            "线性时不变",
            "lti",
            "拉普拉斯",
            "laplace",
            "采样定理",
            "z变换",
            "z transform",
        ),
    ),
    CourseDefinition(
        slug="circuits",
        name="电子电路与系统",
        board="circuit",
        aliases=(
            "电子电路与系统",
            "electronic circuits and systems",
            "电子电路",
            "电路",
            "模拟电路",
            "模电",
        ),
        topics=("基尔霍夫", "运算放大器", "运放", "滤波器", "放大电路", "负反馈"),
    ),
    CourseDefinition(
        slug="digital",
        name="数字电路",
        board="circuit",
        aliases=("数字电路", "数字逻辑", "digital logic", "数电"),
        topics=("布尔代数", "逻辑门", "有限状态机", "状态机", "verilog", "时序逻辑"),
    ),
)


def _normalize(value: str) -> str:
    return re.sub(r"[\s\-_()（）《》·]", "", str(value or "").casefold())


def _course_payload(course: CourseDefinition, confidence: float, evidence: list[str]) -> dict:
    return {
        "slug": course.slug,
        "name": course.name,
        "board": course.board,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "evidence": evidence[:5],
    }


def match_named_course(text: str) -> dict | None:
    """Match an explicitly named course without guessing from generic learning words."""

    normalized = _normalize(text)
    matches: list[tuple[int, CourseDefinition, str]] = []
    for course in COURSES:
        for alias in (course.slug, *course.aliases):
            normalized_alias = _normalize(alias)
            if normalized_alias and normalized_alias in normalized:
                matches.append((len(normalized_alias), course, alias))
    if not matches:
        return None

    _, course, alias = max(matches, key=lambda item: item[0])
    return _course_payload(course, 0.98, [f"课程名：{alias}"])


def infer_course(texts: Iterable[str], sources: Iterable[str] = ()) -> dict | None:
    """Infer a course from a RAG query and retrieved source metadata.

    A direct course name is authoritative. Topic-only inference requires a clear winner,
    so a generic request such as “帮我理解这个知识点” never receives a guessed route.
    """

    text_values = [str(value or "") for value in texts]
    source_values = [str(value or "") for value in sources]
    combined_text = _normalize("\n".join(text_values))
    combined_sources = _normalize("\n".join(source_values))
    scores: list[tuple[int, CourseDefinition, list[str]]] = []

    for course in COURSES:
        score = 0
        evidence: list[str] = []
        for alias in (course.slug, *course.aliases):
            normalized_alias = _normalize(alias)
            if normalized_alias and normalized_alias in combined_text:
                score += 8 + min(4, len(normalized_alias) // 2)
                evidence.append(f"提问：{alias}")
            if normalized_alias and normalized_alias in combined_sources:
                score += 10 + min(4, len(normalized_alias) // 2)
                evidence.append(f"资料来源：{alias}")
        for topic in course.topics:
            normalized_topic = _normalize(topic)
            if normalized_topic and normalized_topic in combined_text:
                score += 4
                evidence.append(f"知识点：{topic}")
            if normalized_topic and normalized_topic in combined_sources:
                score += 5
                evidence.append(f"资料来源知识点：{topic}")
        scores.append((score, course, evidence))

    ranked = sorted(scores, key=lambda item: item[0], reverse=True)
    top_score, course, evidence = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0
    if top_score < 4 or top_score == runner_up:
        return None

    confidence = top_score / (top_score + 3)
    return _course_payload(course, confidence, evidence)
