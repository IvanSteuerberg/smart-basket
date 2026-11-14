"""Decision rules of the product classifier: the section and the name choose the leaf.

Pure and deterministic (decisions 0004, 0007 and 0015): the section narrows the taxonomy to an
allowed subtree, the name picks a leaf inside it, and anything doubtful goes to the review
queue instead of a guess (precision over recall).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from smart_basket.matching.names import Hit, NameMatch

#: A leaf named by the product, and a leaf taken from a section that maps to it.
LEAF_CONFIDENCE = 0.9
SECTION_CONFIDENCE = 0.8


@dataclass(frozen=True, slots=True)
class Section:
    """The taxonomy node a chain section maps to, with what it allows and what contains it."""

    key: str | None
    is_leaf: bool
    #: Keys of the nodes above the section node, innermost first.
    ancestors: frozenset[str]
    #: Keys of the leaves the product may take: the node's subtree and, if it is a leaf, its
    #: parent group's subtree (the section mixes products its chain filed nearby).
    allowed_leaves: frozenset[str]


@dataclass(frozen=True, slots=True)
class Candidate:
    """A leaf a human may choose for a product left in the review queue, and why it is one."""

    category_key: str
    why: str


@dataclass(frozen=True, slots=True)
class Decision:
    """The leaf of a product, or a review with the leaves a human should choose from."""

    category_key: str | None
    confidence: float | None
    candidates: tuple[Candidate, ...] = ()

    @property
    def in_review(self) -> bool:
        return self.category_key is None


def decide(match: NameMatch, section: Section, leaf_keys: frozenset[str]) -> Decision:
    """Assign the leaf of a product, or send it to the review queue.

    `leaf_keys` are the keys of every leaf of the taxonomy, so a name that only names groups
    is told apart from one that names a leaf.
    """
    leaves = tuple(hit for hit in match.hits if hit.key in leaf_keys)
    groups = tuple(hit for hit in match.hits if hit.key not in leaf_keys)

    if leaves:
        return _from_leaves(leaves, section)
    if section.is_leaf:
        return _from_section(section, groups)
    return Decision(
        category_key=None,
        confidence=None,
        candidates=tuple(
            Candidate(key, "the section maps to a group: choose the leaf of the product")
            for key in sorted(section.allowed_leaves)
        ),
    )


def _from_leaves(leaves: tuple[Hit, ...], section: Section) -> Decision:
    """The name names at least one leaf: only an unambiguous leaf inside the section wins.

    Leaves inside the section are preferred, so a word the section files elsewhere does not
    drag an otherwise clear product to the review queue. Leaves are ranked by the length of
    the form that matched, so "leche condensada" beats "leche"; two leaves inside the section
    matched with equally long forms are a tie for the review queue.
    """
    inside = tuple(hit for hit in leaves if hit.key in section.allowed_leaves)
    if inside:
        tied = _most_specific(inside)
        if len(tied) > 1:
            return _review_with(
                tied,
                "the name names this leaf as one of several equally specific ones",
                section,
            )
        return Decision(category_key=tied[0].key, confidence=LEAF_CONFIDENCE)
    return _review_with(
        _most_specific(leaves),
        "the name names this leaf, outside the section's subtree",
        section,
    )


def _most_specific(hits: tuple[Hit, ...]) -> tuple[Hit, ...]:
    """The hits with the longest matched form, so "leche condensada" beats "leche"."""
    longest = max(hit.length for hit in hits)
    return tuple(hit for hit in hits if hit.length == longest)


def _review_with(hits: tuple[Hit, ...], why: str, section: Section) -> Decision:
    """A review naming the `hits` and the section's own leaf, without duplicate keys."""
    return Decision(
        category_key=None,
        confidence=None,
        candidates=_unique(Candidate(hit.key, why) for hit in sorted(hits, key=lambda h: h.key))
        + _section_candidates(section),
    )


def _from_section(section: Section, groups: tuple[Hit, ...]) -> Decision:
    """The section is a leaf and the name names no leaf: take the section's leaf.

    A group named in the product must contain that leaf ("fruta" for a product filed under
    "plátano"); a group that does not is a conflict for the review queue.
    """
    assert section.key is not None  # is_leaf implies a node
    outside = [hit.key for hit in groups if hit.key not in section.ancestors]
    if outside:
        return Decision(
            category_key=None,
            confidence=None,
            candidates=tuple(
                Candidate(key, "the name names a group that does not contain the section's leaf")
                for key in sorted(outside)
            )
            + _section_candidates(section),
        )
    return Decision(category_key=section.key, confidence=SECTION_CONFIDENCE)


def _section_candidates(section: Section) -> tuple[Candidate, ...]:
    if section.key is None or not section.is_leaf:
        return ()
    return (Candidate(section.key, "the section's own leaf"),)


def _unique(candidates: Iterable[Candidate]) -> tuple[Candidate, ...]:
    """Candidates by key, keeping the first reason of each."""
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.category_key, candidate)
    return tuple(unique.values())
