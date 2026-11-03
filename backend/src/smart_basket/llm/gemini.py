"""Gemini API fallback (decision 0005). It only ever receives the list text (NFR-06)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from smart_basket.llm.base import LLMError

API = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(
        self, api_key: str, model: str, timeout: float = 30.0, client: httpx.Client | None = None
    ) -> None:
        self.model = model
        self._client = client or httpx.Client(
            base_url=API, timeout=timeout, headers={"x-goog-api-key": api_key}
        )

    def _generate(self, body: dict[str, Any]) -> str:
        try:
            response = self._client.post(f"/models/{self.model}:generateContent", json=body)
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"gemini request failed: {exc}") from exc

    def generate_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        text = self._generate(
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            }
        )
        try:
            return json.loads(text)
        except ValueError as exc:
            raise LLMError("gemini returned invalid JSON") from exc

    def generate_text(self, prompt: str) -> str:
        return self._generate(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0},
            }
        )
