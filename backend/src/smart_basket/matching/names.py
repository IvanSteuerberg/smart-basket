"""What a product name says: the taxonomy terms it names and the variants that change equivalence.

The forms and the matching rules are the preprocessor's (decision 0014): this module only reads
them to collect *every* term a name names, which the line preprocessor never needs, and the
equivalence variants. No personal data and no collected data live here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from smart_basket.preprocessor import Preprocessor
from smart_basket.preprocessor import rules_es as R
from smart_basket.preprocessor.text import Token, same_word, tokenize

#: Prefix of a detected flavour ("sabor:fresa"); the rest is the folded flavour.
FLAVOUR = "sabor"


@dataclass(frozen=True, slots=True)
class Hit:
    """A taxonomy term named in the product, with the length of the form that matched."""

    key: str
    length: int


@dataclass(frozen=True, slots=True)
class NameMatch:
    """Every taxonomy term the name names and the canonical variants found in it."""

    hits: tuple[Hit, ...]
    variant_keys: tuple[str, ...]


def name_match(preprocessor: Preprocessor, name: str) -> NameMatch:
    """Match a product name against the lexicon terms and its equivalence variants.

    Brands are removed first, as in `Preprocessor.preprocess`; forms, plurals and connectors
    are the preprocessor's, so a name matches exactly what a shopper's line would match.
    """
    _, without_brand, _ = preprocessor._find_brand(tokenize(name))
    variants, _ = preprocessor._match_variants(without_brand)
    return NameMatch(
        hits=_hits(preprocessor, without_brand),
        variant_keys=_variant_keys(preprocessor, variants, without_brand),
    )


def _hits(preprocessor: Preprocessor, tokens: Sequence[Token]) -> tuple[Hit, ...]:
    """Every generic term whose form appears in the name, longest matched form per term."""
    keys = [
        token.key
        for token in tokens
        if token.kind in ("word", "num") and token.key not in R.CONNECTORS
    ]
    lengths: dict[str, int] = {}
    for form, _order, term in preprocessor.generic_forms:
        size = len(form)
        for start in range(len(keys) - size + 1):
            if all(same_word(keys[start + i], form[i]) for i in range(size)):
                lengths[term.key] = max(lengths.get(term.key, 0), size)
                break
    return tuple(Hit(key, length) for key, length in sorted(lengths.items()))


def _variant_keys(
    preprocessor: Preprocessor, found: Sequence[tuple[str, list[Token]]], tokens: Sequence[Token]
) -> tuple[str, ...]:
    """The equivalence-changing variants of the name, plus its flavour, sorted and unique."""
    canonical = {
        term.name: term.key for _form, term in preprocessor.variant_forms if term.canonical
    }
    keys = [canonical[name] for name, _matched in found if name in canonical]
    # The flavour stops where an equivalence variant starts ("sabor fresa sin lactosa").
    taken = {id(token) for name, matched in found if name in canonical for token in matched}
    flavour = _flavour(tokens, taken)
    if flavour is not None:
        keys.append(f"{FLAVOUR}:{flavour}")
    return tuple(sorted(set(keys)))


def _flavour(tokens: Sequence[Token], taken: set[int]) -> str | None:
    """ "sabor <words>" up to the next connector or the end of the name, folded."""
    keys = [token.key for token in tokens]
    if FLAVOUR not in keys:
        return None
    words: list[str] = []
    for token in tokens[keys.index(FLAVOUR) + 1 :]:
        if token.kind != "word" or token.key in R.CONNECTORS or id(token) in taken:
            break
        words.append(token.key)
    return " ".join(words) or None


def variant_key(keys: Sequence[str]) -> str:
    """The sorted, `|`-joined variant keys of a canonical product, or `''`."""
    return "|".join(sorted(set(keys)))


def canonical_name(leaf_name: str, keys: Sequence[str], names: Mapping[str, str]) -> str:
    """«Leche — sin lactosa», «Petit suisse — sabor fresa»: the leaf and its variants."""
    labels = [_label(key, names) for key in keys]
    return leaf_name if not labels else f"{leaf_name} — {', '.join(labels)}"


def _label(key: str, names: Mapping[str, str]) -> str:
    if key.startswith(f"{FLAVOUR}:"):
        return key.replace(":", " ", 1)
    return names.get(key, key)
