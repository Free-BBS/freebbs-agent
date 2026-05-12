from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Protocol

from ..config import AgentConfig


class EmbeddingClient(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


@dataclass
class LocalEmbeddingClient:
    model_name: str
    output_dim: int = 384
    local_model_dir: str | None = None
    local_files_only: bool = False
    hf_endpoint: str | None = None
    _model: object | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [self._normalize(vector) for vector in self._encode(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_sentence_transformer()
        if model is not None:
            vectors = model.encode(texts, normalize_embeddings=False)
            return [list(map(float, vector)) for vector in vectors]
        return [self._hash_embedding(text) for text in texts]

    def _get_sentence_transformer(self):
        if self._model is not None:
            return self._model

        model_path = self._resolve_model_path()
        if not model_path:
            return None

        if self.hf_endpoint:
            os.environ.setdefault("HF_ENDPOINT", self.hf_endpoint)

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            return None
        try:
            self._model = SentenceTransformer(
                model_path,
                local_files_only=True,
            )
            return self._model
        except Exception:
            # Network-restricted environments may fail downloading model weights.
            # Fall back to deterministic hash embeddings so indexing can continue.
            return None

    def _resolve_model_path(self) -> str | None:
        if self.local_model_dir:
            local_path = self.local_model_dir.strip()
            if local_path and os.path.isdir(local_path):
                return local_path
            return None

        if os.path.isdir(self.model_name):
            return self.model_name

        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            return None

        kwargs = {
            "repo_id": self.model_name,
            "local_files_only": self.local_files_only,
        }
        if self.hf_endpoint:
            kwargs["endpoint"] = self.hf_endpoint

        try:
            return snapshot_download(**kwargs)
        except Exception:
            return None

    def _hash_embedding(self, text: str) -> list[float]:
        values = [0.0] * self.output_dim
        if not text:
            return values
        for token in text.split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for idx in range(self.output_dim):
                byte_value = digest[idx % len(digest)]
                values[idx] += (byte_value / 255.0) - 0.5
        return values

    def _normalize(self, values: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return values
        return [value / norm for value in values]


@dataclass
class OpenAICompatibleEmbeddingClient:
    api_key: str
    model: str
    base_url: str | None = None

    def __post_init__(self):
        from openai import OpenAI

        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self.model, input=texts)
        return [list(map(float, item.embedding)) for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def build_embedding_client(config: AgentConfig) -> EmbeddingClient:
    provider = (config.rag_embedding_provider or "local").strip().lower()
    if provider in {"local", "local_model"}:
        return LocalEmbeddingClient(
            model_name=config.rag_local_embedding_model,
            output_dim=config.rag_local_embedding_dim,
            local_model_dir=config.rag_local_model_dir,
            local_files_only=config.rag_local_files_only,
            hf_endpoint=config.rag_hf_endpoint,
        )
    if provider in {"api", "openai", "openai_compatible"}:
        api_key = config.rag_embedding_api_key or config.api_key
        if not api_key:
            raise ValueError("RAG embedding API key is required for api provider")
        return OpenAICompatibleEmbeddingClient(
            api_key=api_key,
            model=config.rag_embedding_model,
            base_url=config.rag_embedding_base_url or config.base_url,
        )
    raise ValueError(f"Unsupported RAG embedding provider: {config.rag_embedding_provider}")
