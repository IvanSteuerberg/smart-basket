"""Embedding providers against `httpx.MockTransport` (never the real network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from smart_basket.config import Settings
from smart_basket.llm.base import LLMError
from smart_basket.llm.embeddings import (
    GeminiEmbeddingProvider,
    OllamaEmbeddingProvider,
    embedding_provider_from_settings,
)

DIMENSIONS = 768


def _vector(seed: float = 0.0) -> list[float]:
    return [seed] * DIMENSIONS


def _gemini(handler: Any, api_key: str = "secret") -> GeminiEmbeddingProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiEmbeddingProvider(
        api_key=api_key, model="gemini-embedding-001", dimensions=DIMENSIONS, client=client
    )


def _ollama(handler: Any, dimensions: int = DIMENSIONS) -> OllamaEmbeddingProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaEmbeddingProvider(
        base_url="http://ollama:11434",
        model="nomic-embed-text",
        dimensions=dimensions,
        client=client,
    )


def test_gemini_posts_batch_with_key_and_dimensions():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"embeddings": [{"values": _vector(i)} for i in range(len(body["requests"]))]},
        )

    vectors = _gemini(handler, api_key="top-secret").embed(["Leche entera", "Yogur natural"])

    assert len(vectors) == 2
    assert all(len(vector) == DIMENSIONS for vector in vectors)

    request = seen[0]
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-embedding-001:batchEmbedContents"
    )
    assert request.headers["x-goog-api-key"] == "top-secret"
    body = json.loads(request.content)
    assert [r["model"] for r in body["requests"]] == ["models/gemini-embedding-001"] * 2
    assert all(r["outputDimensionality"] == DIMENSIONS for r in body["requests"])
    assert body["requests"][0]["content"]["parts"][0]["text"] == "Leche entera"


def test_gemini_batches_in_chunks_of_100():
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        count = len(body["requests"])
        batch_sizes.append(count)
        return httpx.Response(
            200, json={"embeddings": [{"values": _vector()} for _ in range(count)]}
        )

    vectors = _gemini(handler).embed([f"item {i}" for i in range(250)])

    assert len(vectors) == 250
    assert batch_sizes == [100, 100, 50]


def test_gemini_empty_input_skips_http():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call expected")

    assert _gemini(handler).embed([]) == []


def test_gemini_rejects_wrong_dimensions():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [{"values": [0.0] * 3}]})

    with pytest.raises(LLMError, match="unexpected size"):
        _gemini(handler).embed(["x"])


def test_gemini_rejects_wrong_embedding_count():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [{"values": _vector()}]})

    with pytest.raises(LLMError, match="unexpected size"):
        _gemini(handler).embed(["a", "b"])


def test_gemini_raises_llm_error_on_http_failure_without_leaking_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMError) as excinfo:
        _gemini(handler, api_key="top-secret").embed(["x"])
    assert "top-secret" not in str(excinfo.value)


def test_gemini_raises_llm_error_on_network_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(LLMError):
        _gemini(handler).embed(["x"])


def test_ollama_posts_to_api_embed():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={"embeddings": [_vector() for _ in body["input"]]})

    vectors = _ollama(handler).embed(["Leche entera", "Yogur natural"])

    assert len(vectors) == 2
    assert all(len(vector) == DIMENSIONS for vector in vectors)

    request = seen[0]
    assert str(request.url) == "http://ollama:11434/api/embed"
    assert json.loads(request.content) == {
        "model": "nomic-embed-text",
        "input": ["Leche entera", "Yogur natural"],
    }


def test_ollama_empty_input_skips_http():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call expected")

    assert _ollama(handler).embed([]) == []


def test_ollama_rejects_wrong_dimensions():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.0] * 3]})

    with pytest.raises(LLMError, match="unexpected size"):
        _ollama(handler).embed(["x"])


def test_ollama_raises_llm_error_on_http_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMError):
        _ollama(handler).embed(["x"])


def test_provider_from_settings_builds_gemini_by_default():
    settings = Settings(gemini_api_key="key")
    provider = embedding_provider_from_settings(settings)

    assert isinstance(provider, GeminiEmbeddingProvider)
    assert provider.model == "gemini-embedding-001"
    assert provider.dimensions == 768


def test_provider_from_settings_builds_ollama():
    settings = Settings(
        embedding_provider="ollama", embedding_model="nomic-embed-text", embedding_dimensions=768
    )
    provider = embedding_provider_from_settings(settings)

    assert isinstance(provider, OllamaEmbeddingProvider)
    assert provider.model == "nomic-embed-text"
    assert provider.dimensions == 768


def test_provider_from_settings_requires_gemini_api_key():
    settings = Settings(embedding_provider="gemini", gemini_api_key=None)

    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        embedding_provider_from_settings(settings)


def test_provider_from_settings_rejects_unknown_provider():
    settings = Settings(embedding_provider="bogus")

    with pytest.raises(LLMError, match="unknown embedding provider"):
        embedding_provider_from_settings(settings)
