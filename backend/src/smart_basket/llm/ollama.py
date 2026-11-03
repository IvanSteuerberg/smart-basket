"""Ollama chat API (native on the author's laptop, decision 0005)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from smart_basket.llm.base import LLMError


class OllamaProvider:
    name = "ollama"

    def __init__(
        self, base_url: str, model: str, timeout: float = 30.0, client: httpx.Client | None = None
    ) -> None:
        self.model = model
        self._client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def _chat(self, messages: list[dict[str, str]], **extra: Any) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0, "seed": 42},
            **extra,
        }
        if self.model.startswith(("qwen", "gemma")):
            payload["think"] = False  # as in the benchmark of decision 0005
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"ollama request failed: {exc}") from exc

    def generate_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        content = self._chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            format=schema,
        )
        try:
            return json.loads(content)
        except ValueError as exc:
            raise LLMError("ollama returned invalid JSON") from exc

    def generate_text(self, prompt: str) -> str:
        return self._chat([{"role": "user", "content": prompt}])
