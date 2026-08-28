from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import urlencode

import httpx

from .chunking import SourceDocument


class CourseSnapshotError(RuntimeError):
    pass


def fetch_course_snapshot(config) -> dict[str, Any]:
    socket_path = config.rag_course_snapshot_socket_path
    service_token = config.rag_course_snapshot_token
    if not socket_path or not service_token:
        raise CourseSnapshotError(
            "RAG course snapshot socket and token are required for RAG sync"
        )
    endpoint = config.rag_course_snapshot_endpoint
    if not endpoint.startswith("/"):
        raise CourseSnapshotError("RAG course snapshot endpoint must start with /")

    try:
        with httpx.Client(
            base_url="http://localhost",
            transport=httpx.HTTPTransport(uds=socket_path),
            timeout=httpx.Timeout(config.rag_sync_timeout_seconds),
            trust_env=False,
        ) as client:
            response = client.get(
                endpoint,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {service_token}",
                },
            )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise CourseSnapshotError("course snapshot service is unavailable") from exc

    if response.status_code != 200:
        raise CourseSnapshotError(
            f"course snapshot service returned HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise CourseSnapshotError("course snapshot response is not valid JSON") from exc
    return validate_course_snapshot(payload)


def validate_course_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CourseSnapshotError("course snapshot must be an object")
    revision = payload.get("revision")
    documents = payload.get("documents")
    if isinstance(revision, bool) or not isinstance(revision, (str, int)):
        raise CourseSnapshotError("course snapshot revision is invalid")
    if not isinstance(documents, list) or any(not isinstance(item, dict) for item in documents):
        raise CourseSnapshotError("course snapshot documents are invalid")
    normalized_revision = str(revision).strip()
    if not normalized_revision:
        raise CourseSnapshotError("course snapshot revision is empty")
    return {**payload, "revision": normalized_revision, "documents": documents}


def course_snapshot_documents(
    snapshot: dict[str, Any],
    *,
    web_base_url: str = "",
) -> tuple[list[SourceDocument], dict[str, dict[str, Any]]]:
    documents: list[SourceDocument] = []
    metadata_by_doc_id: dict[str, dict[str, Any]] = {}
    for item in snapshot["documents"]:
        course_slug = _required_text(item, "courseSlug")
        node_id = _required_text(item, "nodeId")
        title = _required_text(item, "title")
        course_name = _required_text(item, "courseName")
        course_code = str(item.get("courseCode") or "").strip()
        source = _knowledge_url(web_base_url, course_slug, node_id)
        prefix_lines = [f"课程：{course_name}", f"课程标识：{course_slug}"]
        if course_code:
            prefix_lines.append(f"课程代码：{course_code}")
        prefix_lines.extend([f"知识点编号：{node_id}", f"知识点：{title}"])
        prefix = "\n".join(prefix_lines)
        base_metadata = {
            "source_type": "course_map",
            "course_id": item.get("courseId"),
            "course_slug": course_slug,
            "course_name": course_name,
            "course_code": course_code,
            "node_id": node_id,
            "title": title,
            "updated_at": str(item.get("updatedAt") or ""),
            "url": source,
            "snapshot_revision": snapshot["revision"],
        }
        sections = [
            ("overview", _overview_text(item)),
            ("basic_info", str(item.get("basicInfoMarkdown") or "").strip()),
            ("knowledge", str(item.get("knowledgeMarkdown") or "").strip()),
            ("applications", str(item.get("applicationsMarkdown") or "").strip()),
        ]
        for section, content in sections:
            if not content:
                continue
            doc_id = f"course_map:{course_slug}:{node_id}:{section}"
            section_title = {
                "overview": "知识点概览与关系",
                "basic_info": "基本信息",
                "knowledge": "核心知识",
                "applications": "应用与拓展",
            }[section]
            documents.append(
                SourceDocument(
                    doc_id=doc_id,
                    source=source,
                    text=f"{prefix}\n\n## {section_title}\n\n{content}",
                )
            )
            metadata_by_doc_id[doc_id] = {**base_metadata, "section": section}
    return documents, metadata_by_doc_id


def _overview_text(item: dict[str, Any]) -> str:
    parts = []
    course_summary = str(item.get("courseSummary") or "").strip()
    summary = str(item.get("summary") or "").strip()
    if course_summary:
        parts.append(f"课程摘要：{course_summary}")
    if summary:
        parts.append(f"知识点摘要：{summary}")

    grouped: dict[str, list[str]] = defaultdict(list)
    for relation in item.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        label = _relation_label(relation)
        target = str(relation.get("title") or relation.get("nodeId") or "").strip()
        node_id = str(relation.get("nodeId") or "").strip()
        if label and target:
            grouped[label].append(f"{target}（{node_id}）" if node_id else target)
    for label in ("前置知识", "后续知识", "相关知识"):
        values = grouped.get(label)
        if values:
            parts.append(f"{label}：{'、'.join(values)}")
    return "\n".join(parts) or "该知识点暂无补充摘要。"


def _relation_label(relation: dict[str, Any]) -> str:
    relation_type = str(relation.get("type") or "")
    direction = str(relation.get("direction") or "")
    if relation_type == "related":
        return "相关知识"
    if relation_type == "ordered" and direction == "incoming":
        return "前置知识"
    if relation_type == "ordered" and direction == "outgoing":
        return "后续知识"
    return ""


def _knowledge_url(base_url: str, course_slug: str, node_id: str) -> str:
    path = f"/knowledge?{urlencode({'course': course_slug, 'point': node_id})}"
    return f"{base_url.rstrip('/')}{path}" if base_url.strip() else path


def _required_text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CourseSnapshotError(f"course snapshot document {key} is required")
    return value.strip()
