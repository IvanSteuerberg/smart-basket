"""Incremental pgvector embeddings and cosine search for the catalog (ADR 0022, I14 E5).

Catalog text is embedded once and kept in `vector(768)` columns (migration 0010). This module
fills only the rows whose `embedding` is still `NULL`, so a re-run over an unchanged catalog
embeds nothing, and it answers the two questions the catalog agent asks: which canonicals are
closest to a product, and which unmatched products cluster together.

All similarity is cosine, computed by PostgreSQL through the `<=>` operator, so the HNSW index
of migration 0010 is used and Python never loads the whole catalog.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.llm.embeddings import EmbeddingProvider

#: The migration fixes every catalog embedding at 768 dimensions (Gemini and Ollama both fit).
EMBEDDING_DIMENSIONS = 768
#: Rows embedded per provider call and per page loaded from the database.
DEFAULT_BATCH_SIZE = 100
#: Minimum cosine similarity that joins two products into the same cluster.
DEFAULT_CLUSTER_SIMILARITY = 0.86
#: Minimum size of a cluster the catalog agent may turn into a new leaf (ADR 0022).
DEFAULT_CLUSTER_SIZE = 3

_MISSING_CANONICALS = """
select cp.id, cp.name, cp.variant_key, cat.name as category_name
from canonical_product cp
join category cat on cat.id = cp.category_id
where cp.embedding is null
order by cp.id
limit :batch_size
"""

_MISSING_PRODUCTS = """
select cp.id, cp.name, cc.name as category_name
from chain_product cp
left join chain_category cc on cc.id = cp.chain_category_id
where cp.embedding is null and cp.is_active
{chain_filter}
order by cp.id
limit :batch_size
"""

_UNMATCHED_PRODUCTS = """
select cp.id, cp.name
from chain_product cp
join chain ch on ch.id = cp.chain_id
where cp.canonical_id is null and cp.embedding is not null and cp.is_active
{chain_filter}
order by cp.id
"""

_SIMILAR_PAIRS = """
select a.id as left_id, b.id as right_id,
       1 - (a.embedding <=> b.embedding) as similarity
from chain_product a
join chain_product b on b.id > a.id
where a.id = any(:ids) and b.id = any(:ids)
  and a.canonical_id is null and b.canonical_id is null
  and a.embedding is not null and b.embedding is not null
  and 1 - (a.embedding <=> b.embedding) >= :min_similarity
"""


@dataclass(frozen=True, slots=True)
class CanonicalMatch:
    """One canonical returned by the nearest-neighbour search, ordered by similarity."""

    canonical_id: int
    category_id: int
    category_key: str
    name: str
    variant_key: str
    similarity: float


@dataclass(frozen=True, slots=True)
class ProductCluster:
    """A connected group of unmatched products whose texts are close enough to share a leaf."""

    product_ids: tuple[int, ...]
    product_names: tuple[str, ...]
    mean_similarity: float


def _vector_literal(vector: Sequence[float]) -> str:
    """Format a vector as pgvector's text input (`[0.1,0.2]`) for `cast(:vec as vector)`."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def build_canonical_text(name: str, category_name: str | None, variant_key: str) -> str:
    """The public text embedded for a canonical: its name, its leaf and its variant."""
    parts = [name.strip()]
    if category_name and category_name.strip():
        parts.append(category_name.strip())
    if variant_key and variant_key.strip():
        parts.append(variant_key.strip())
    return " | ".join(parts)


def build_product_text(name: str, category_name: str | None) -> str:
    """The public text embedded for a chain product: its name and its chain section."""
    parts = [name.strip()]
    if category_name and category_name.strip():
        parts.append(category_name.strip())
    return " | ".join(parts)


def embed_missing_canonicals(
    session: Session, provider: EmbeddingProvider, *, batch_size: int = DEFAULT_BATCH_SIZE
) -> int:
    """Embed every canonical whose `embedding` is still `NULL`; return how many were written."""
    return _embed_missing(
        session,
        provider,
        _MISSING_CANONICALS,
        lambda row: build_canonical_text(row["name"], row["category_name"], row["variant_key"]),
        table="canonical_product",
        batch_size=batch_size,
    )


def embed_missing_products(
    session: Session,
    provider: EmbeddingProvider,
    *,
    chain_code: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Embed every active chain product without a vector; return how many were written."""
    chain_filter = (
        "" if chain_code is None else "and cp.chain_id = (select id from chain where code = :chain)"
    )
    return _embed_missing(
        session,
        provider,
        _MISSING_PRODUCTS.format(chain_filter=chain_filter),
        lambda row: build_product_text(row["name"], row["category_name"]),
        table="chain_product",
        batch_size=batch_size,
        params={} if chain_code is None else {"chain": chain_code},
    )


def nearest_canonicals(
    session: Session, embedding: Sequence[float], *, top_k: int = 5
) -> list[CanonicalMatch]:
    """The `top_k` canonicals closest to `embedding`, by descending cosine similarity."""
    if top_k <= 0:
        return []
    _check_vector(embedding)
    rows = session.execute(
        text(
            "select cp.id as canonical_id, cp.category_id, cat.key as category_key, cp.name, "
            "  cp.variant_key, 1 - (cp.embedding <=> cast(:vec as vector)) as similarity "
            "from canonical_product cp "
            "join category cat on cat.id = cp.category_id "
            "where cp.embedding is not null and cp.merged_into is null "
            "order by cp.embedding <=> cast(:vec as vector) asc "
            "limit :top_k"
        ),
        {"vec": _vector_literal(embedding), "top_k": top_k},
    ).mappings()
    return [
        CanonicalMatch(
            canonical_id=row["canonical_id"],
            category_id=row["category_id"],
            category_key=row["category_key"],
            name=row["name"],
            variant_key=row["variant_key"],
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]


def cluster_unmatched_products(
    session: Session,
    *,
    chain_code: str | None = None,
    min_similarity: float = DEFAULT_CLUSTER_SIMILARITY,
    min_cluster_size: int = DEFAULT_CLUSTER_SIZE,
) -> list[ProductCluster]:
    """Group unmatched embedded products into connected components of cosine similarity.

    Two products are connected when their cosine similarity is at least `min_similarity`; every
    connected component of `min_cluster_size` or more products becomes one `ProductCluster`,
    with the mean of the similarities that joined it. Ordered by their smallest product id.
    """
    if min_cluster_size < 2:
        raise ValueError("min_cluster_size must be at least 2")
    chain_filter = "" if chain_code is None else "and ch.code = :chain"
    params: dict[str, object] = {} if chain_code is None else {"chain": chain_code}
    products = list(
        session.execute(
            text(_UNMATCHED_PRODUCTS.format(chain_filter=chain_filter)), params
        ).mappings()
    )
    if len(products) < min_cluster_size:
        return []
    names = {row["id"]: row["name"] for row in products}
    ids = sorted(names)

    edges = session.execute(
        text(_SIMILAR_PAIRS), {"ids": ids, "min_similarity": min_similarity}
    ).all()
    parent = {product_id: product_id for product_id in ids}

    def find(product_id: int) -> int:
        while parent[product_id] != product_id:
            parent[product_id] = parent[parent[product_id]]
            product_id = parent[product_id]
        return product_id

    for left, right, _similarity in edges:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    members: dict[int, list[int]] = {}
    for product_id in ids:
        members.setdefault(find(product_id), []).append(product_id)
    similarity_sums: dict[int, float] = {}
    similarity_counts: dict[int, int] = {}
    for left, _right, similarity in edges:
        root = find(left)
        similarity_sums[root] = similarity_sums.get(root, 0.0) + float(similarity)
        similarity_counts[root] = similarity_counts.get(root, 0) + 1

    clusters = []
    for root, component in members.items():
        if len(component) < min_cluster_size:
            continue
        component = sorted(component)
        mean = similarity_sums.get(root, 0.0) / similarity_counts[root]
        clusters.append(
            ProductCluster(
                product_ids=tuple(component),
                product_names=tuple(names[product_id] for product_id in component),
                mean_similarity=round(mean, 6),
            )
        )
    clusters.sort(key=lambda cluster: cluster.product_ids[0])
    return clusters


def _embed_missing(
    session: Session,
    provider: EmbeddingProvider,
    select_sql: str,
    text_for: Callable[[Mapping[str, object]], str],
    *,
    table: str,
    batch_size: int,
    params: Mapping[str, object] | None = None,
) -> int:
    """Page through rows with a missing vector, embed their text and store the result."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    total = 0
    while True:
        rows = list(
            session.execute(
                text(select_sql), {**(params or {}), "batch_size": batch_size}
            ).mappings()
        )
        if not rows:
            return total
        vectors = provider.embed([text_for(row) for row in rows])
        if len(vectors) != len(rows):
            raise ValueError(f"provider returned {len(vectors)} embeddings for {len(rows)} texts")
        for row, vector in zip(rows, vectors, strict=True):
            _check_vector(vector)
            session.execute(
                text(
                    f"update {table} set embedding = cast(:vec as vector) "
                    "where id = :id and embedding is null"
                ),
                {"vec": _vector_literal(vector), "id": row["id"]},
            )
        total += len(rows)
        if len(rows) < batch_size:
            return total


def _check_vector(vector: Sequence[float]) -> None:
    """Reject a vector the fixed `vector(768)` column could not hold."""
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"expected a {EMBEDDING_DIMENSIONS}-dimension vector, got {len(vector)}")
    if any(not math.isfinite(float(value)) for value in vector):
        raise ValueError("embedding contains a non-finite value")
