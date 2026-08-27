from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .chunking import SourceDocument

SUPPORTED_TEXT_SUFFIXES = {".md", ".txt", ".rst", ".py", ".c", ".cpp", ".h"}
SUPPORTED_BINARY_SUFFIXES = {".pdf"}


def clone_or_update_repo(repo_url: str, target_dir: str) -> Path:
    target_path = Path(target_dir)
    if (target_path / ".git").exists():
        # Git submodules are normally checked out at a pinned commit with a
        # detached HEAD. Pulling there fails and would also defeat the pinned
        # revision. Use the checked-out content as-is; update only regular
        # branch checkouts.
        branch = subprocess.run(
            ["git", "-C", str(target_path), "symbolic-ref", "--short", "-q", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if branch.returncode != 0:
            return target_path
        subprocess.run(
            ["git", "-C", str(target_path), "pull", "--ff-only"],
            check=True,
        )
        return target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", repo_url, str(target_path)],
        check=True,
    )
    return target_path


def load_documents_from_directory(
    root_dir: str,
    *,
    min_chars: int = 20,
    source_prefix: str = "",
) -> list[SourceDocument]:
    root = Path(root_dir)
    files = sorted(path for path in root.rglob("*") if path.is_file())
    documents: list[SourceDocument] = []

    for path in files:
        if _is_ignored(path):
            continue
        if path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES | SUPPORTED_BINARY_SUFFIXES:
            continue

        text = extract_text(path)
        if len(text.strip()) < min_chars:
            continue

        rel = path.relative_to(root)
        source = f"{source_prefix.rstrip('/')}/{rel}" if source_prefix else str(rel)
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
        documents.append(
            SourceDocument(
                doc_id=f"doc_{digest}",
                source=source,
                text=text,
            )
        )

    return documents


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF parsing requires optional dependency: pypdf") from exc

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    return ""


def _is_ignored(path: Path) -> bool:
    ignored_parts = {".git", ".github", "__pycache__", ".venv"}
    return any(part in ignored_parts for part in path.parts)
