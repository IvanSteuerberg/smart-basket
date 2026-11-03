"""The provider protocol: JSON output constrained by a schema, and free text."""

from __future__ import annotations

from typing import Any, Protocol

from smart_basket.config import Settings


class LLMError(RuntimeError):
    """The provider failed, timed out or returned invalid JSON."""


class LLMProvider(Protocol):
    name: str

    def generate_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """One call whose answer must follow `schema`; raises LLMError otherwise."""
        ...

    def generate_text(self, prompt: str) -> str:
        """Free text (the explanation of a recommendation)."""
        ...


def provider_from_settings(settings: Settings) -> LLMProvider | None:
    """The configured provider, or None in rules-only mode (`LLM_PROVIDER=none`, FR-41)."""
    from smart_basket.llm.gemini import GeminiProvider
    from smart_basket.llm.ollama import OllamaProvider

    if settings.llm_provider == "ollama":
        return OllamaProvider(
            settings.ollama_url, settings.ollama_model, timeout=settings.llm_timeout_seconds
        )
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMError("LLM_PROVIDER=gemini needs GEMINI_API_KEY")
        return GeminiProvider(
            settings.gemini_api_key, settings.gemini_model, timeout=settings.llm_timeout_seconds
        )
    return None
