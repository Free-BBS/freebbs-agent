from __future__ import annotations

from pathlib import Path

from ..server_settings import (
    SETTINGS_UNAVAILABLE_MESSAGE,
    ServerSettingsError,
    ServerSettingsProvider,
)


def resolve_under_course_root(configured_path: str, course_materials_root: str) -> str:
    candidate = Path(configured_path)
    if not course_materials_root or candidate.is_absolute():
        return str(candidate)

    root = Path(course_materials_root).resolve()
    resolved_candidate = (root / candidate).resolve()

    try:
        resolved_candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("configured RAG path escapes the course materials root") from exc

    return str(resolved_candidate)


def resolve_rag_store_paths(
    index_path: str,
    metadata_path: str,
    course_materials_root: str,
) -> tuple[str, str]:
    return (
        resolve_under_course_root(index_path, course_materials_root),
        resolve_under_course_root(metadata_path, course_materials_root),
    )


def resolve_rag_manifest_path(manifest_path: str, course_materials_root: str) -> str:
    return resolve_under_course_root(manifest_path, course_materials_root)


def course_materials_root_for_config(config) -> str:
    if config.server_settings_partially_configured:
        raise ServerSettingsError(invalidate_cache=True)
    if not config.server_settings_enabled:
        return config.course_materials_root

    return ServerSettingsProvider(
        config.settings_socket_path or "",
        config.agent_service_token or "",
        timeout_seconds=config.settings_timeout_seconds,
        cache_ttl_seconds=config.settings_cache_ttl_seconds,
        stale_ttl_seconds=config.settings_stale_ttl_seconds,
    ).get_snapshot().course_materials_root


def resolve_configured_rag_store_paths(config) -> tuple[str, str]:
    try:
        course_materials_root = course_materials_root_for_config(config)
    except ServerSettingsError:
        raise RuntimeError(SETTINGS_UNAVAILABLE_MESSAGE) from None

    return resolve_rag_store_paths(
        config.rag_index_path,
        config.rag_metadata_path,
        course_materials_root,
    )


def resolve_configured_rag_manifest_path(config) -> str:
    try:
        course_materials_root = course_materials_root_for_config(config)
    except ServerSettingsError:
        raise RuntimeError(SETTINGS_UNAVAILABLE_MESSAGE) from None
    return resolve_rag_manifest_path(
        config.rag_index_manifest_path,
        course_materials_root,
    )
