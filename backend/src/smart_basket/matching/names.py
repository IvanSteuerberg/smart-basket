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
from smart_basket.preprocessor.text import Token, tokenize

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
    are the preprocessor's, so a name matches exactly what a shopper's line would match. The
    words of a flavour ("sabor fresa") name the variant, not the leaves those words would
    otherwise hit.
    """
    tokens = tokenize(name)
    _, without_brand, brand_tokens = preprocessor.find_brand(tokens)
    variants, _ = preprocessor.find_variants(without_brand)
    keys = [term.key for term, _matched in variants if term.canonical]
    # The flavour stops where an equivalence variant or the brand starts.
    stop = {id(token) for token in brand_tokens}
    stop |= {id(token) for term, matched in variants if term.canonical for token in matched}
    flavour, flavour_tokens = _flavour(tokens, stop)
    if flavour is not None:
        keys.append(f"{FLAVOUR}:{flavour}")
    masked = [token for token in without_brand if id(token) not in flavour_tokens]
    return NameMatch(hits=_hits(preprocessor, masked), variant_keys=tuple(sorted(set(keys))))


def _hits(preprocessor: Preprocessor, tokens: Sequence[Token]) -> tuple[Hit, ...]:
    """Every generic term whose form appears in the name, longest matched form per term."""
    lengths: dict[str, int] = {}
    for hit in preprocessor.generic_hits(tokens):
        lengths[hit.term.key] = max(lengths.get(hit.term.key, 0), hit.length)
    return tuple(Hit(key, length) for key, length in sorted(lengths.items()))


def _flavour(tokens: Sequence[Token], stop: set[int]) -> tuple[str | None, set[int]]:
    """ "sabor <words>" up to the end, an equivalence variant or a brand, folded.

    An introductory "a" or "de" is skipped ("sabor a fresa"), "y" and "con" stay inside the
    flavour ("sabor fresa y platano"), and the tokens it consumed are returned so its words
    do not also name a leaf.
    """
    keys = [token.key for token in tokens]
    if FLAVOUR not in keys:
        return None, set()
    start = keys.index(FLAVOUR)
    consumed = {id(tokens[start])}
    words: list[str] = []
    index = start + 1
    if index < len(tokens) and tokens[index].key in ("a", "de"):
        consumed.add(id(tokens[index]))
        index += 1
    for token in tokens[index:]:
        if id(token) in stop or token.kind != "word":
            break
        if token.key in R.CONNECTORS and token.key not in ("y", "con"):
            break
        words.append(token.key)
        consumed.add(id(token))
    while words and words[-1] in ("y", "con"):
        words.pop()
    return (" ".join(words) or None), consumed


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
