import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, DocumentChunk
from app.services.embeddings import embed_texts
from app.services.metadata import normalize_filter_values
from app.services.tracing import traceable


KEYWORD_SEARCH_CONFIG = "simple"
QUERY_TERM_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}")


@dataclass(slots=True)
class RetrievedChunk:
    chunk: DocumentChunk
    document: Document
    retrieval_methods: list[str] = field(default_factory=list)
    vector_distance: float | None = None
    keyword_score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float = 0.0

    @property
    def match_type(self) -> str:
        if len(self.retrieval_methods) > 1:
            return "hybrid"
        if self.retrieval_methods:
            return self.retrieval_methods[0]
        return "vector"


def apply_metadata_filters(statement, metadata_filters: dict[str, Any] | None):
    if not metadata_filters:
        return statement

    document_types = normalize_filter_values(metadata_filters.get("document_types"))
    topics = normalize_filter_values(metadata_filters.get("topics"))
    entities = normalize_filter_values(metadata_filters.get("entities"))
    languages = normalize_filter_values(metadata_filters.get("languages"))

    if document_types:
        statement = statement.where(
            or_(*[Document.extracted_metadata.contains({"document_type": value}) for value in document_types])
        )
    if topics:
        statement = statement.where(
            or_(*[Document.extracted_metadata.contains({"topics": [value]}) for value in topics])
        )
    if entities:
        statement = statement.where(
            or_(*[Document.extracted_metadata.contains({"entities": [value]}) for value in entities])
        )
    if languages:
        statement = statement.where(
            or_(*[Document.extracted_metadata.contains({"language": value}) for value in languages])
        )
    return statement


def tokenize_query_terms(content: str) -> set[str]:
    return {match.group(0).lower() for match in QUERY_TERM_PATTERN.finditer(content)}


def normalize_vector_score(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - distance))


def compute_term_overlap(query_terms: set[str], item: RetrievedChunk) -> float:
    if not query_terms:
        return 0.0

    haystack = f"{item.document.filename} {item.chunk.content}".lower()
    matched_terms = sum(1 for term in query_terms if term in haystack)
    return matched_terms / len(query_terms)


def rerank_candidates(content: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
    if not candidates:
        return []

    query_terms = tokenize_query_terms(content)
    max_rrf_score = max((item.rrf_score for item in candidates), default=0.0)
    max_keyword_score = max((item.keyword_score or 0.0 for item in candidates), default=0.0)

    for item in candidates:
        normalized_rrf = item.rrf_score / max_rrf_score if max_rrf_score > 0 else 0.0
        normalized_keyword = (item.keyword_score or 0.0) / max_keyword_score if max_keyword_score > 0 else 0.0
        vector_score = normalize_vector_score(item.vector_distance)
        overlap_score = compute_term_overlap(query_terms, item)
        hybrid_bonus = 0.08 if item.match_type == "hybrid" else 0.0

        item.rerank_score = (
            normalized_rrf * 0.4
            + vector_score * 0.3
            + normalized_keyword * 0.2
            + overlap_score * 0.1
            + hybrid_bonus
        )

    return sorted(
        candidates,
        key=lambda item: (
            -item.rerank_score,
            -item.rrf_score,
            item.vector_distance if item.vector_distance is not None else 1.0,
            -(item.keyword_score or 0.0),
        ),
    )


def upsert_candidate(
    candidates: dict[UUID, RetrievedChunk],
    chunk: DocumentChunk,
    document: Document,
) -> RetrievedChunk:
    existing = candidates.get(chunk.id)
    if existing is not None:
        return existing

    item = RetrievedChunk(chunk=chunk, document=document)
    candidates[chunk.id] = item
    return item


def fetch_vector_candidates(
    db: Session,
    user_id: UUID,
    content: str,
    metadata_filters: dict[str, Any] | None = None,
) -> list[tuple[DocumentChunk, Document, float]]:
    try:
        [query_embedding] = embed_texts([content])
    except Exception:
        return []

    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
    statement = (
        select(DocumentChunk, Document, distance)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.user_id == user_id, Document.status == "completed")
    )
    statement = apply_metadata_filters(statement, metadata_filters)
    rows = list(db.execute(statement.order_by(distance).limit(settings.retrieval_vector_limit)).all())
    return [
        (chunk, document, float(chunk_distance))
        for chunk, document, chunk_distance in rows
        if chunk_distance is not None and float(chunk_distance) <= settings.retrieval_max_distance
    ]


def fetch_keyword_candidates(
    db: Session,
    user_id: UUID,
    content: str,
    metadata_filters: dict[str, Any] | None = None,
) -> list[tuple[DocumentChunk, Document, float]]:
    query_terms = tokenize_query_terms(content)
    if not query_terms:
        return []

    normalized_query = " ".join(sorted(query_terms))
    ts_query = func.plainto_tsquery(KEYWORD_SEARCH_CONFIG, normalized_query)
    search_vector = func.to_tsvector(KEYWORD_SEARCH_CONFIG, DocumentChunk.content)
    keyword_score = func.ts_rank_cd(search_vector, ts_query).label("keyword_score")
    statement = (
        select(DocumentChunk, Document, keyword_score)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.user_id == user_id,
            Document.status == "completed",
            search_vector.op("@@")(ts_query),
        )
    )
    statement = apply_metadata_filters(statement, metadata_filters)
    rows = list(db.execute(statement.order_by(keyword_score.desc()).limit(settings.retrieval_keyword_limit)).all())
    return [
        (chunk, document, float(match_score))
        for chunk, document, match_score in rows
        if match_score is not None and float(match_score) > 0.0
    ]


def fuse_candidates(
    vector_results: list[tuple[DocumentChunk, Document, float]],
    keyword_results: list[tuple[DocumentChunk, Document, float]],
) -> list[RetrievedChunk]:
    candidates: dict[UUID, RetrievedChunk] = {}

    for rank, (chunk, document, distance) in enumerate(vector_results, start=1):
        item = upsert_candidate(candidates, chunk, document)
        item.vector_distance = distance
        item.vector_rank = rank
        item.rrf_score += 1.0 / (settings.retrieval_rrf_k + rank)
        if "vector" not in item.retrieval_methods:
            item.retrieval_methods.append("vector")

    for rank, (chunk, document, keyword_score) in enumerate(keyword_results, start=1):
        item = upsert_candidate(candidates, chunk, document)
        item.keyword_score = keyword_score
        item.keyword_rank = rank
        item.rrf_score += 1.0 / (settings.retrieval_rrf_k + rank)
        if "keyword" not in item.retrieval_methods:
            item.retrieval_methods.append("keyword")

    fused = sorted(
        candidates.values(),
        key=lambda item: (
            -item.rrf_score,
            item.vector_distance if item.vector_distance is not None else 1.0,
            -(item.keyword_score or 0.0),
        ),
    )
    return fused[: settings.retrieval_candidate_limit]


@traceable(name="retrieve-hybrid-context", run_type="retriever")
def retrieve_relevant_chunks(
    db: Session,
    user_id: UUID,
    content: str,
    metadata_filters: dict[str, Any] | None = None,
) -> list[RetrievedChunk]:
    vector_results = fetch_vector_candidates(db, user_id, content, metadata_filters)
    keyword_results = fetch_keyword_candidates(db, user_id, content, metadata_filters)
    fused_candidates = fuse_candidates(vector_results, keyword_results)
    reranked_candidates = rerank_candidates(content, fused_candidates)
    return reranked_candidates[: settings.retrieval_limit]
