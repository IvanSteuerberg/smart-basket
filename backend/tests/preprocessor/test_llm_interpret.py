"""Merging LLM answers for unresolved lines, with fake providers (no network)."""

from smart_basket.llm import LLMError, interpret_unresolved


class FakeProvider:
    name = "fake"

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def generate_json(self, system, user, schema):
        self.calls.append(user)
        if self.error:
            raise self.error
        return self.answer

    def generate_text(self, prompt):
        return ""


def test_only_unresolved_lines_are_sent(pp):
    result = pp.preprocess("leche, algo para la cena, pan")
    provider = FakeProvider(
        {
            "items": [
                {"item": "tortilla de patatas", "quantity": 1, "unit": "ud", "ambiguous": False}
            ]
        }
    )
    out = interpret_unresolved(result, provider)
    assert provider.calls == ["algo para la cena"]
    assert [i["item"] for i in out.items] == ["leche", "tortilla de patatas", "pan"]
    assert out.llm_used
    assert not out.degraded


def test_no_call_when_everything_resolves(pp):
    provider = FakeProvider()
    out = interpret_unresolved(pp.preprocess("leche, pan"), provider)
    assert provider.calls == []
    assert not out.degraded


def test_degraded_mode_without_provider_or_on_errors(pp):
    result = pp.preprocess("leche, algo para la cena")
    for provider in (
        None,
        FakeProvider(error=LLMError("timeout")),
        FakeProvider({"items": [{"item": 3}]}),
    ):
        out = interpret_unresolved(result, provider)
        assert out.degraded
        assert [i["item"] for i in out.items] == ["leche", "algo para la cena"]
