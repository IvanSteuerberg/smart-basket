"""Rule-based preprocessor v1 (decision 0005 point 3, FR-01, FR-41; rules in decision 0014).

Turns a free-text shopping list into items with the shape of the LLM item schema
(`item`, `quantity`, `unit`, `brand`, `attributes`, `ambiguous`), resolving what rules can
and marking the rest as unresolved, to be sent to the LLM. Deterministic and offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from rapidfuzz.distance import DamerauLevenshtein

from smart_basket.preprocessor import rules_es as R
from smart_basket.preprocessor.lexicon import BrandTerm, GenericTerm, Lexicon, UnitTerm
from smart_basket.preprocessor.text import Token, fold, join, same_word, tokenize, words

UNITS = ("ud", "kg", "g", "l", "ml")
SPLIT_RE = re.compile(r"\r?\n|;|(?<!\d),|,(?!\d)|\s\+\s|•|·")
EDGE_CHARS = " \t-*.:"


@dataclass(frozen=True, slots=True)
class PreprocessedItem:
    line: int
    raw: str
    item: str
    quantity: Decimal
    unit: str
    brand: str | None
    attributes: tuple[str, ...]
    ambiguous: bool
    resolved: bool
    reasons: tuple[str, ...] = ()
    generic_key: str | None = None
    canonical_id: int | None = None
    corrections: tuple[str, ...] = ()
    context: str | None = None
    #: The other alternatives of "pasta/espaguetis" or "pasta o espaguetis" (any will do);
    #: `item` names them all and the match uses the most specific one.
    alternatives: tuple[str, ...] = ()

    @property
    def needs_llm(self) -> bool:
        return not self.resolved

    def to_item(self) -> dict[str, Any]:
        """The item in the shape of the LLM item schema (experiments/llm-benchmark)."""
        q = self.quantity
        return {
            "item": self.item,
            "quantity": int(q) if q == q.to_integral_value() else float(q),
            "unit": self.unit,
            "brand": self.brand,
            "attributes": list(self.attributes),
            "ambiguous": self.ambiguous,
        }


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    items: tuple[PreprocessedItem, ...]

    @property
    def llm_lines(self) -> tuple[int, ...]:
        """Lines (0-based) the LLM has to interpret."""
        return tuple(i.line for i in self.items if i.needs_llm)

    @property
    def resolved_share(self) -> float:
        return sum(i.resolved for i in self.items) / len(self.items) if self.items else 1.0

    def to_schema(self) -> dict[str, Any]:
        return {"items": [i.to_item() for i in self.items]}

    def llm_input(self) -> str:
        """The unresolved lines, one per row: all the LLM receives (NFR-06)."""
        return "\n".join(i.raw for i in self.items if i.needs_llm)


@dataclass(slots=True)
class _Quantity:
    value: Decimal = Decimal(1)
    unit: str = "ud"
    found: bool = False
    container: list[Token] = field(default_factory=list)


class Preprocessor:
    def __init__(
        self,
        lexicon: Lexicon,
        typo_similarity: float = 0.8,
        min_typo_length: int = 4,
        min_segment_length: int = 6,
    ) -> None:
        self.typo_similarity = typo_similarity
        self.min_typo_length = min_typo_length
        self.min_segment_length = min_segment_length
        self.units: dict[str, UnitTerm] = {fold(u.form): u for u in lexicon.units()}
        self.generic = list(lexicon.generic_terms())
        self.generic_by_key = {g.key: g for g in self.generic}

        # Forms as content-word tuples (connectors removed), longest first.
        self.generic_forms: list[tuple[tuple[str, ...], int, GenericTerm]] = []
        for order, term in enumerate(self.generic):
            for form in (term.name, *term.forms):
                content = tuple(w for w in words(form) if w not in R.CONNECTORS)
                if content:
                    self.generic_forms.append((content, order, term))
        self.variant_forms = sorted(
            ((words(f), v) for v in lexicon.variants() for f in (v.name, *v.forms)),
            key=lambda fv: -len(fv[0]),
        )
        self.brands: list[tuple[str, BrandTerm]] = sorted(
            ((self._compact(words(a)), b) for b in lexicon.brands() for a in b.aliases),
            key=lambda ab: -len(ab[0]),
        )
        #: Lexicon forms with a number in their name ("omega 3", "7 cereales"): there the
        #: number is part of the product, not a quantity.
        all_forms = (
            *(f for g in self.generic for f in (g.name, *g.forms)),
            *(f for v in lexicon.variants() for f in (v.name, *v.forms)),
            *(a for b in lexicon.brands() for a in (b.name, *b.aliases)),
        )
        self.numbered_forms = sorted(
            {words(f) for f in all_forms if any(t.kind == "num" for t in tokenize(f))}
        )

        lexical = set()
        self.display: dict[str, str] = {}
        for term in self.generic:
            for form in (term.name, *term.forms):
                self._learn(form, lexical)
        for variant in lexicon.variants():
            for form in (variant.name, *variant.forms):
                self._learn(form, lexical)
        for brand in lexicon.brands():
            for alias in (brand.name, *brand.aliases):
                lexical.update(words(alias))
        rule_words = {
            *R.CONNECTORS,
            *R.FILLERS,
            *R.NUMBER_WORDS,
            *R.FRACTION_WORDS,
            *R.MULTIPLIERS,
            *R.AMBIGUITY_WORDS,
            *R.PURPOSE_WORDS,
            *self.units,
            *R.ABBREVIATIONS,
            "sin",
            *(w for p in R.AMBIGUITY_PHRASES for w in p),
            *(w for k, v in R.SYNONYMS.items() for w in (*k, *v)),
        }
        self.vocabulary = lexical | rule_words
        #: Candidates for typo correction: product words only, sorted for determinism.
        self.typo_candidates = sorted(w for w in lexical if len(w) >= 3)
        self.segment_pieces = {w for w in self.vocabulary if len(w) >= 3} | {"de", "con", "al"}

    def _learn(self, form: str, lexical: set[str]) -> None:
        for token in tokenize(form):
            lexical.add(token.key)
            self.display.setdefault(token.key, token.text)

    @staticmethod
    def _compact(keys: tuple[str, ...] | list[str]) -> str:
        return "".join(keys).replace("-", "")

    def _display(self, key: str) -> str | None:
        """The lexicon's spelling (with accents) of a folded word, plurals included."""
        if key in self.display:
            return self.display[key]
        for suffix in ("es", "s"):
            stem = key[: -len(suffix)]
            if key.endswith(suffix) and stem in self.display:
                return _pluralize(self.display[stem], suffix)
        return None

    def _known(self, key: str) -> bool:
        if key in self.vocabulary:
            return True
        return any(key.endswith(s) and key[: -len(s)] in self.vocabulary for s in ("es", "s"))

    # Public API ---------------------------------------------------------------

    def preprocess(self, text: str) -> PreprocessResult:
        parts = [p.strip(EDGE_CHARS) for p in SPLIT_RE.split(text)]
        items: list[PreprocessedItem] = []
        for part in parts:
            part = re.sub(r"^(?:y|e)\s+", "", part, flags=re.IGNORECASE).strip(EDGE_CHARS)
            if not part:
                continue
            for piece in self._split_on_and(part):
                items.append(self._line(piece, len(items)))
        return PreprocessResult(tuple(items))

    def _split_on_and(self, part: str) -> list[str]:
        """Split "pan y leche" when both halves resolve on their own ("kilo y medio" stays).
        A line with alternatives resolves on one of them, so it is tried as well
        ("leche/zumo y huevos")."""
        whole = self._line(part, 0)
        halves = re.split(r"\s+y\s+", part, maxsplit=1)
        if (whole.resolved and not whole.alternatives) or len(halves) != 2:
            return [part]
        a, b = self._line(halves[0], 0), self._line(halves[1], 0)
        return halves if a.resolved and b.resolved else [part]

    # One line -----------------------------------------------------------------

    def _line(self, raw: str, index: int) -> PreprocessedItem:
        corrections: list[str] = []
        tokens = self._merge_slashes(tokenize(raw))
        tokens = self._fix_words(tokens, corrections)
        tokens = self._expand_abbreviations(tokens, corrections)
        tokens = self._apply_synonyms(tokens, corrections)
        keys = [t.key for t in tokens]
        ambiguous = any(k in R.AMBIGUITY_WORDS for k in keys) or any(
            _find(keys, list(p)) is not None for p in R.AMBIGUITY_PHRASES
        )

        qty, tokens_after_qty = self._extract_quantity(tokens)
        brand, rest, brand_tokens = self._find_brand(tokens_after_qty)
        # "pasta/espaguetis", "pasta o espaguetis": either will do. Match the first one
        # that names a specific product, else the first one found, else the first.
        groups = _alternatives(rest)
        matches = [self._match_generic(g) for g in groups]
        pick = next((k for k, m in enumerate(matches) if m[0] and not m[0].vague), None)
        if pick is None:
            pick = next((k for k, m in enumerate(matches) if m[0]), 0)
        seq = groups[pick]
        generic, span, rest_after = matches[pick]
        if generic is None and qty.container:
            # "2 bolsas de basura": the container word belongs to the product.
            generic2, span2, rest2 = self._match_generic(qty.container + seq)
            seq = groups[pick] = qty.container + seq
            if generic2 is not None:
                generic, span, rest_after = generic2, span2, rest2
                qty.container = []
        if generic is None and brand is not None and brand.implies in self.generic_by_key:
            generic = self.generic_by_key[brand.implies]
        elif generic is None and brand is not None and len(groups) == 1:
            # The brand swallowed the whole line ("gallo", "pastas gallo") and says nothing
            # about the product: try the generic match again with the brand tokens back in.
            generic2, span2, rest2 = self._match_generic(tokens_after_qty)
            if generic2 is not None:
                brand_ids = {id(t) for t in brand_tokens}
                generic, span = generic2, span2
                rest_after = [t for t in rest2 if id(t) not in brand_ids]
                seq = tokens_after_qty
                brand = None

        attributes, rest_after = self._match_variants(rest_after)
        unknown, context = self._leftovers(rest_after)
        # The other alternatives are shown, not resolved: their unknown words do not block.
        texts: list[str] = []
        alternatives: list[str] = []
        for k, group in enumerate(groups):
            if k == pick:
                texts.append(self._item_text(generic, span, seq, attributes))
                continue
            other, other_span, other_rest = matches[k]
            other_attributes, other_rest = self._match_variants(other_rest)
            context = context or self._leftovers(other_rest)[1]
            text = self._item_text(other, other_span, group, other_attributes)
            if text:
                texts.append(text)
                alternatives.append(text)

        reasons = []
        if ambiguous:
            reasons.append("ambiguous")
        if generic is None:
            reasons.append("unknown_item")
        elif generic.vague:
            ambiguous = True
            reasons.append("vague_item")
        if unknown:
            reasons.append("unknown_words:" + " ".join(unknown))

        return PreprocessedItem(
            line=index,
            raw=raw,
            item=" o ".join(texts),
            quantity=qty.value,
            unit=qty.unit,
            brand=brand.name if brand else None,
            attributes=tuple(name for name, _ in attributes),
            ambiguous=ambiguous,
            resolved=not reasons,
            reasons=tuple(reasons),
            generic_key=generic.key if generic else None,
            canonical_id=generic.canonical_id if generic else None,
            corrections=tuple(corrections),
            context=context,
            alternatives=tuple(alternatives),
        )

    # Normalization ------------------------------------------------------------

    @staticmethod
    def _merge_slashes(tokens: list[Token]) -> list[Token]:
        """Join "1/2" into one number, and "s/", "c/" (expanded later to "sin", "con")."""
        out: list[Token] = []
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if (
                t.kind == "num"
                and i + 2 < len(tokens)
                and tokens[i + 1].key == "/"
                and tokens[i + 2].kind == "num"
            ):
                den = Decimal(tokens[i + 2].key.replace(",", "."))
                if den:
                    value = Decimal(t.key.replace(",", ".")) / den
                    out.append(Token(f"{t.text}/{tokens[i + 2].text}", str(value), "num"))
                    i += 3
                    continue
            if t.key == "/" and out and out[-1].key in ("s", "c"):
                prev = out.pop()
                out.append(Token(prev.text + "/", prev.key + "/", "word"))
            else:
                out.append(t)
            i += 1
        return out

    def _fix_words(self, tokens: list[Token], corrections: list[str]) -> list[Token]:
        """Restore accents, split joined words and correct typos against the lexicon."""
        out: list[Token] = []
        for t in tokens:
            if t.kind != "word":
                out.append(t)
                continue
            if self._known(t.key) or len(t.key) < self.min_typo_length:
                shown = self._display(t.key)
                if t.text == t.key and shown:
                    t = t.with_text(shown, t.changed)
                out.append(t)
                continue
            pieces = self._segment(t.key) if len(t.key) >= self.min_segment_length else None
            if pieces:
                corrections.append(f"{t.text} -> {' '.join(pieces)}")
                out.extend(Token(self.display.get(p, p), p, "word", "segmented") for p in pieces)
                continue
            word = self._closest(t.key)
            if word is not None:
                corrections.append(f"{t.text} -> {self.display.get(word, word)}")
                out.append(Token(self.display.get(word, word), word, "word", "typo"))
                continue
            out.append(t)
        return out

    def _closest(self, key: str) -> str | None:
        """Most similar product word (Damerau-Levenshtein), first in sorted order on ties."""
        best, best_score = None, self.typo_similarity
        for word in self.typo_candidates:
            if abs(len(word) - len(key)) > 2:
                continue
            score = DamerauLevenshtein.normalized_similarity(key, word)
            if score > best_score or (best is None and score >= best_score):
                best, best_score = word, score
        return best

    def _segment(self, key: str) -> list[str] | None:
        """Fewest vocabulary pieces that spell `key` ("pandemolde" -> pan de molde)."""
        n = len(key)
        best: list[list[str] | None] = [None] * (n + 1)
        best[0] = []
        for i in range(1, n + 1):
            for j in range(0, i):
                prefix = best[j]
                piece = key[j:i]
                if prefix is None or not (
                    piece in self.segment_pieces or (len(piece) >= 4 and self._known(piece))
                ):
                    continue
                candidate = [*prefix, piece]
                if best[i] is None or len(candidate) < len(best[i]):
                    best[i] = candidate
        result = best[n]
        return result if result and len(result) >= 2 else None

    def _expand_abbreviations(self, tokens: list[Token], corrections: list[str]) -> list[Token]:
        out: list[Token] = []
        for t in tokens:
            expansion = R.ABBREVIATIONS.get(t.key)
            if t.kind == "word" and expansion:
                if expansion != (t.key,):
                    corrections.append(f"{t.text} -> {' '.join(expansion)}")
                out.extend(
                    Token(self.display.get(w, w), w, "word", "abbreviation") for w in expansion
                )
            else:
                out.append(t)
        return out

    def _apply_synonyms(self, tokens: list[Token], corrections: list[str]) -> list[Token]:
        for source, target in sorted(R.SYNONYMS.items(), key=lambda kv: -len(kv[0])):
            keys = [t.key for t in tokens]
            at = _find(keys, list(source))
            if at is None or source == target:
                continue
            new = [Token(self.display.get(w, w), w, "word", "synonym") for w in target]
            corrections.append(f"{' '.join(source)} -> {' '.join(target)}")
            tokens = tokens[:at] + new + tokens[at + len(source) :]
        return tokens

    # Quantities ---------------------------------------------------------------

    def _number(self, tokens: list[Token], i: int, words_ok: bool) -> Decimal | None:
        if i >= len(tokens):
            return None
        t = tokens[i]
        if t.kind == "num":
            return Decimal(t.key.replace(",", "."))
        if words_ok and t.key in R.NUMBER_WORDS:
            return R.NUMBER_WORDS[t.key]
        return None

    def _unit(self, tokens: list[Token], i: int) -> UnitTerm | None:
        return self.units.get(tokens[i].key) if i < len(tokens) else None

    def _extract_quantity(self, tokens: list[Token]) -> tuple[_Quantity, list[Token]]:
        for i in range(len(tokens)):
            found = self._quantity_at(tokens, i)
            if found is None:
                continue
            qty, end = found
            if qty.value <= 0:
                continue
            rest = tokens[:i] + tokens[end:]
            if i == 0 and rest and rest[0].key in ("de", "del"):
                if qty.container:
                    qty.container.append(rest[0])
                rest = rest[1:]
            qty.found = True
            return qty, rest
        return _Quantity(), tokens

    def _quantity_at(self, tokens: list[Token], i: int) -> tuple[_Quantity, int] | None:
        key = tokens[i].key
        # "6 x 1,5 l", "6x1,5l": packs of a size.
        a = self._number(tokens, i, words_ok=True)
        if a is not None and i + 3 < len(tokens) and tokens[i + 1].key in R.MULTIPLIERS:
            b = self._number(tokens, i + 2, words_ok=False)
            unit = self._unit(tokens, i + 3)
            if b is not None and unit is not None and not unit.container:
                return _Quantity(a * b * unit.factor, unit.unit), i + 4
        # "pack de 3", "pack 6".
        if key in ("pack", "packs"):
            j = i + 2 if i + 1 < len(tokens) and tokens[i + 1].key == "de" else i + 1
            n = self._number(tokens, j, words_ok=True)
            if n is not None:
                return _Quantity(n, "ud"), j + 1
        # "x8", "x 3".
        if key in R.MULTIPLIERS and key != "por":
            n = self._number(tokens, i + 1, words_ok=False)
            if n is not None:
                return _Quantity(n, "ud"), i + 2
        # "3x", "3 x yogures".
        n = self._number(tokens, i, words_ok=(i == 0))
        if (
            n is not None
            and i + 1 < len(tokens)
            and tokens[i + 1].key in R.MULTIPLIERS
            and tokens[i + 1].key != "por"
            and self._number(tokens, i + 2, words_ok=False) is None
        ):
            return _Quantity(n, "ud"), i + 2
        # [number] [fraction] [de] unit [y medio]: "2 l", "medio kilo", "un cuarto de kilo",
        # "kilo y medio", "una docena", "6 bricks".
        value = self._number(tokens, i, words_ok=(i == 0))
        j = i + (value is not None)
        if j < len(tokens) and tokens[j].key in R.FRACTION_WORDS:
            frac = R.FRACTION_WORDS[tokens[j].key]
            value = frac if value is None else value * frac
            j += 1
            if j + 1 < len(tokens) and tokens[j].key == "de" and self._unit(tokens, j + 1):
                j += 1
        unit = self._unit(tokens, j)
        if unit is not None and (value is not None or (j == i == 0 and not unit.container)):
            amount = value if value is not None else Decimal(1)
            end = j + 1
            if (
                end + 1 < len(tokens)
                and tokens[end].key == "y"
                and tokens[end + 1].key in ("medio", "media")
            ):
                amount += Decimal("0.5")
                end += 2
            qty = _Quantity(amount * unit.factor, unit.unit)
            if unit.container:
                qty.container = [tokens[j]]
            return qty, end
        if (
            value is not None
            and j == i + 1
            and (tokens[i].kind == "num" or i == 0)
            and self._bare_count(tokens, i)
        ):
            return _Quantity(value, "ud"), i + 1
        return None

    def _bare_count(self, tokens: list[Token], i: int) -> bool:
        """Whether a number without unit or multiplier counts units: "3 yogures" at the start
        and "huevos 12" at the end do; "omega 3" (a lexicon name), "A3" (glued to its word),
        "leche 0%" and "pan 7 cereales" (followed by a word that is not a unit) do not."""
        after = tokens[i + 1] if i + 1 < len(tokens) else None
        if after is not None and after.key == "%":
            return False
        if self._in_name(tokens, i):
            return False
        if i == 0:
            return True
        if tokens[i].glued and tokens[i - 1].kind == "word":
            return False
        return after is None or (after.kind == "word" and after.key in R.FILLERS)

    def _in_name(self, tokens: list[Token], i: int) -> bool:
        """The number at `i` is inside a lexicon form ("omega 3", "7 cereales")."""
        keys = [t.key for t in tokens]
        for form in self.numbered_forms:
            for k, word in enumerate(form):
                start = i - k
                if word != keys[i] or start < 0 or start + len(form) > len(keys):
                    continue
                if all(same_word(keys[start + m], form[m]) for m in range(len(form))):
                    return True
        return False

    # Brands, generic terms, variants ------------------------------------------

    def _find_brand(self, tokens: list[Token]) -> tuple[BrandTerm | None, list[Token], list[Token]]:
        for size in (3, 2, 1):
            for i in range(len(tokens) - size + 1):
                compact = self._compact([t.key for t in tokens[i : i + size]])
                for alias, brand in self.brands:
                    if alias == compact:
                        return brand, tokens[:i] + tokens[i + size :], tokens[i : i + size]
        return None, tokens, []

    def _match_generic(
        self, tokens: list[Token]
    ) -> tuple[GenericTerm | None, list[Token], list[Token]]:
        # Numbers left after the quantity belong to the name ("omega 3").
        content = [
            i
            for i, t in enumerate(tokens)
            if t.kind in ("word", "num") and t.key not in R.CONNECTORS
        ]
        keys = [tokens[i].key for i in content]
        best = None
        for form, order, term in self.generic_forms:
            n = len(form)
            for pos in range(len(keys) - n + 1):
                if all(same_word(keys[pos + k], form[k]) for k in range(n)):
                    rank = (-n, pos, order)
                    if best is None or rank < best[0]:
                        best = (rank, pos, n, term)
                    break
        if best is None:
            return None, [], tokens
        _, pos, n, term = best
        start, end = content[pos], content[pos + n - 1] + 1
        return term, tokens[start:end], tokens[:start] + tokens[end:]

    def _match_variants(
        self, rest: list[Token]
    ) -> tuple[list[tuple[str, list[Token]]], list[Token]]:
        found: list[tuple[str, list[Token]]] = []
        for form, variant in self.variant_forms:
            if any(name == variant.name for name, _ in found):
                continue
            at = _find([t.key for t in rest], list(form), plural=True)
            if at is not None:
                found.append((variant.name, rest[at : at + len(form)]))
                rest = rest[:at] + rest[at + len(form) :]
        return found, rest

    def _leftovers(self, tokens: list[Token]) -> tuple[list[str], str | None]:
        """Unknown words, and a purpose phrase ("para el finde") kept as context."""
        unknown: list[str] = []
        context = None
        keys = [t.key for t in tokens]
        if "para" in keys:
            at = keys.index("para")
            tail = tokens[at:]
            if all(
                t.key in R.FILLERS or t.key in R.PURPOSE_WORDS or t.kind != "word" for t in tail
            ):
                context = " ".join(t.text for t in tail)
                tokens = tokens[:at]
        for t in tokens:
            if t.kind != "word" or t.key in R.FILLERS or t.key in R.AMBIGUITY_WORDS:
                continue
            if t.key in R.PURPOSE_WORDS or any(t.key in p for p in R.AMBIGUITY_PHRASES):
                continue
            unknown.append(t.text)
        return unknown, context

    def _item_text(
        self,
        generic: GenericTerm | None,
        span: list[Token],
        seq: list[Token],
        attributes: list[tuple[str, list[Token]]],
    ) -> str:
        """The user's own words for the item, corrected: the product and its variants, with
        the connectors between them ("helado de chocolate") and the numbers of its name
        ("leche 0%"), without quantity or brand."""
        if generic is None:
            texts = [t for t in seq if t.kind == "word" or _name_number(t)]
            while texts and texts[0].key in R.FILLERS:
                texts.pop(0)
            while texts and texts[-1].key in R.FILLERS:
                texts.pop()
            return join(texts)
        if not span:
            head = [generic.name]
            return " ".join([*head, *(t.text for _, toks in attributes for t in toks)])
        if generic.vague:
            return join(span)
        variant_ids = {id(t) for _, toks in attributes for t in toks}
        position = {id(t): i for i, t in enumerate(seq)}
        start, end = position[id(span[0])], position[id(span[-1])]
        after = [i for i, t in enumerate(seq) if id(t) in variant_ids and i > end]
        last = max(after, default=end)
        while last + 1 < len(seq) and _name_number(seq[last + 1]):
            last += 1
        # Head first, then the variants and numbers written after it with their connectors
        # ("helado de chocolate"), then any variant written before it ("s/lactosa yogures").
        out = [t for i, t in enumerate(seq) if start <= i <= end]
        out += [
            t
            for i, t in enumerate(seq)
            if end < i <= last
            and (id(t) in variant_ids or t.key in R.CONNECTORS or _name_number(t))
        ]
        out += [t for i, t in enumerate(seq) if i < start and id(t) in variant_ids]
        return join(out)


def _name_number(t: Token) -> bool:
    """A number (or "%") left after the quantity: part of the name ("0%", "A3")."""
    return t.kind == "num" or t.key == "%"


def _alternatives(tokens: list[Token]) -> list[list[Token]]:
    """Split "pasta/espaguetis" and "pasta o espaguetis" into alternatives. A slash between
    numbers is a fraction ("1/2", merged before) and "o" only separates two words."""
    groups: list[list[Token]] = [[]]
    for i, t in enumerate(tokens):
        before = tokens[i - 1] if i > 0 else None
        after = tokens[i + 1] if i + 1 < len(tokens) else None
        if before is not None and after is not None and groups[-1]:
            slash = t.key == "/" and "word" in (before.kind, after.kind)
            either = t.key == "o" and before.kind == after.kind == "word"
            if slash or either:
                groups.append([])
                continue
        groups[-1].append(t)
    return [g for g in groups if g] or [[]]


_UNACCENT = str.maketrans("áéíóú", "aeiou")


def _pluralize(word: str, suffix: str) -> str:
    """ "limón" + "es" -> "limones" (the stress mark of a final syllable drops), else append."""
    if suffix == "es" and word and word[-1] not in "aeiouáéíóú":
        for i in range(len(word) - 1, -1, -1):
            if word[i] in "aeiouáéíóú":
                return word[:i] + word[i].translate(_UNACCENT) + word[i + 1 :] + suffix
    return word + suffix


def _find(keys: list[str], pattern: list[str], plural: bool = False) -> int | None:
    n = len(pattern)
    for i in range(len(keys) - n + 1):
        window = keys[i : i + n]
        if window == pattern or (plural and all(map(same_word, window, pattern, strict=True))):
            return i
    return None
