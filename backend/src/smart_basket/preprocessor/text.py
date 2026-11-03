"""Text helpers: folding, tokens and word comparison."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace

TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)?|[^\W\d_]+(?:-[^\W\d_]+)*|[×/%]", re.UNICODE)


def fold(text: str) -> str:
    """Lower case without accents or diaeresis ("Plátanos" -> "platanos", "piña" -> "pina")."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@dataclass(frozen=True, slots=True)
class Token:
    """A word, number or symbol of a list line. `key` is folded; `text` is what is shown."""

    text: str
    key: str
    kind: str  # "word", "num" or "sym"
    #: How the token was changed: "", "abbreviation", "segmented", "typo", "synonym".
    changed: str = ""

    def with_text(self, text: str, changed: str) -> Token:
        return replace(self, text=text, key=fold(text), changed=changed)


def tokenize(line: str) -> list[Token]:
    tokens = []
    for match in TOKEN_RE.finditer(line.lower()):
        raw = match.group()
        kind = "num" if raw[0].isdigit() else ("word" if raw[0].isalpha() else "sym")
        tokens.append(Token(raw, fold(raw), kind))
    return tokens


def same_word(a: str, b: str) -> bool:
    """Equal folded words, ignoring a plural -s or -es ("tomate" ~ "tomates")."""
    if a == b:
        return True
    if len(a) > len(b):
        a, b = b, a
    return b in (a + "s", a + "es")


def words(text: str) -> tuple[str, ...]:
    return tuple(t.key for t in tokenize(text))
