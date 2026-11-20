"""Embedding providers for public catalog text (ADR 0022, iteration 14 task E2).

Public catalog text is embedded with Gemini (`gemini-embedding-001`, 768 dimensions); a local
Ollama instance is also supported. Both return one vector per input, in input order, and never
receive private shopper data.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Sequence
from typing import Protocol

import httpx

from smart_basket.config import Settings
from smart_basket.llm.base import LLMError

API = "https://generativelanguage.googleapis.com/v1beta"
#: Gemini's batch endpoint accepts at most 100 requests per call.
BATCH_SIZE = 100
DEFAULT_RETRY_DELAYS = (5.0, 15.0, 30.0, 60.0)


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One `dimensions`-long vector per text, in input order; raises LLMError otherwise."""
        ...


class GeminiEmbeddingProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        dimensions: int = 768,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)
        self._retry_delays = retry_delays

    def _embed_batch(self, chunk: Sequence[str]) -> list[list[float]]:
        body = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": self.dimensions,
                    "taskType": "SEMANTIC_SIMILARITY",
                }
                for text in chunk
            ]
        }
        url = f"{API}/models/{self.model}:batchEmbedContents"
        try:
            response = self._post_with_retry(url, body)
            response.raise_for_status()
            vectors = [
                [float(value) for value in embedding["values"]]
                for embedding in response.json()["embeddings"]
            ]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise LLMError(f"gemini embeddings request failed: {exc}") from exc
        if len(vectors) != len(chunk) or any(len(v) != self.dimensions for v in vectors):
            raise LLMError(
                f"gemini returned {len(vectors)} embeddings of unexpected size "
                f"(expected {len(chunk)} of {self.dimensions})"
            )
        return vectors

    def _post_with_retry(self, url: str, body: dict[str, object]) -> httpx.Response:
        headers = {"x-goog-api-key": self._api_key}
        for attempt in range(len(self._retry_delays) + 1):
            response = self._client.post(url, json=body, headers=headers)
            if response.status_code != 429 or attempt >= len(self._retry_delays):
                return response
            delay = self._retry_delays[attempt]
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                with contextlib.suppress(ValueError):
                    delay = max(delay, float(retry_after))
            time.sleep(delay)
        return response  # pragma: no cover

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(self._embed_batch(texts[start : start + BATCH_SIZE]))
        return vectors


class OllamaEmbeddingProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        dimensions: int = 768,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self._client.post(
                f"{self._base_url}/api/embed",
                json={"model": self.model, "input": list(texts)},
            )
            response.raise_for_status()
            vectors = [
                [float(value) for value in vector] for vector in response.json()["embeddings"]
            ]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise LLMError(f"ollama embeddings request failed: {exc}") from exc
        if len(vectors) != len(texts) or (
            self.dimensions > 0 and any(len(vector) != self.dimensions for vector in vectors)
        ):
            raise LLMError(
                f"ollama returned {len(vectors)} embeddings of unexpected size "
                f"(expected {len(texts)} of {self.dimensions})"
            )
        return vectors


def embedding_provider_from_settings(
    settings: Settings, *, client: httpx.Client | None = None
) -> EmbeddingProvider:
    """The configured embedding provider; raises LLMError if it cannot be built."""
    if settings.embedding_provider == "ollama":
        return OllamaEmbeddingProvider(
            settings.ollama_url,
            settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=settings.llm_timeout_seconds,
            client=client,
        )
    if settings.embedding_provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMError("EMBEDDING_PROVIDER=gemini needs GEMINI_API_KEY")
        return GeminiEmbeddingProvider(
            settings.gemini_api_key,
            settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=settings.llm_timeout_seconds,
            client=client,
        )
    raise LLMError(f"unknown embedding provider: {settings.embedding_provider}")
