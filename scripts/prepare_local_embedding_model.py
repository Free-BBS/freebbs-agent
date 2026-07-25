#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a local embedding model via mirror and verify it can be loaded offline."
    )
    parser.add_argument(
        "--model-id",
        default="BAAI/bge-small-zh-v1.5",
        help="HuggingFace model id for local embedding.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/models/bge-small-zh-v1.5",
        help="Directory to store local model files.",
    )
    parser.add_argument(
        "--hf-endpoint",
        default="https://hf-mirror.com",
        help="HuggingFace mirror endpoint.",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "huggingface", "modelscope"],
        default="auto",
        help="Model download source. 'auto' tries huggingface mirror first, then modelscope.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip offline load and embedding verification.",
    )
    return parser.parse_args()


def download_huggingface(model_id: str, output_dir: str, hf_endpoint: str) -> str:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required. Install sentence-transformers first.") from exc

    os.environ["HF_ENDPOINT"] = hf_endpoint
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "300")
    local_dir = str(Path(output_dir).resolve())
    Path(local_dir).mkdir(parents=True, exist_ok=True)

    downloaded_path = snapshot_download(
        repo_id=model_id,
        endpoint=hf_endpoint,
        local_dir=local_dir,
    )
    return downloaded_path


def download_modelscope(model_id: str, output_dir: str) -> str:
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError as exc:
        raise RuntimeError("modelscope is required. Install with: pip install modelscope") from exc

    local_dir = str(Path(output_dir).resolve())
    Path(local_dir).mkdir(parents=True, exist_ok=True)
    downloaded_path = snapshot_download(model_id=model_id, cache_dir=local_dir)
    return downloaded_path


def download_model(model_id: str, output_dir: str, hf_endpoint: str, source: str) -> tuple[str, str]:
    if source == "huggingface":
        return download_huggingface(model_id, output_dir, hf_endpoint), "huggingface"
    if source == "modelscope":
        return download_modelscope(model_id, output_dir), "modelscope"

    hf_error = None
    try:
        return download_huggingface(model_id, output_dir, hf_endpoint), "huggingface"
    except Exception as exc:
        hf_error = exc

    try:
        return download_modelscope(model_id, output_dir), "modelscope"
    except Exception as ms_exc:
        raise RuntimeError(
            "Download failed on both huggingface mirror and modelscope. "
            f"HF error: {hf_error}; ModelScope error: {ms_exc}"
        ) from ms_exc


def verify_model(local_model_dir: str) -> int:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("sentence-transformers is required for verification.") from exc

    model = SentenceTransformer(local_model_dir, local_files_only=True)
    vectors = model.encode(
        [
            "傅里叶变换在信号处理中有什么作用？",
            "DRC 检查在原理图阶段有什么作用？",
        ],
        normalize_embeddings=True,
    )
    return int(len(vectors[0]))


def main() -> None:
    args = parse_args()
    path, used_source = download_model(args.model_id, args.output_dir, args.hf_endpoint, args.source)

    print("Model download finished:")
    print(f"- model_id: {args.model_id}")
    print(f"- local_dir: {path}")
    print(f"- source: {used_source}")
    if used_source == "huggingface":
        print(f"- hf_endpoint: {args.hf_endpoint}")

    if args.skip_verify:
        return

    dim = verify_model(path)
    print("Offline verification passed:")
    print(f"- embedding_dim: {dim}")
    print("- status: usable")


if __name__ == "__main__":
    main()
