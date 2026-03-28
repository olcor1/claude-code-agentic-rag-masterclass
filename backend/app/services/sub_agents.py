import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, DocumentChunk
from app.services.folders import visible_document_clause
from app.services.metadata import extract_json_object, get_completion_text
from app.services.redaction import ConversationRedactionSession
from app.services.retrieval import RetrievedChunk
from app.services.tracing import traceable
from app.utils.text import normalize_text


sub_agent_client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
FULL_DOCUMENT_HINT_PATTERN = re.compile(
    r"\b("
    r"summarize|summary|overview|outline|walk me through|walk through|deep dive|review|critique|"
    r"analyze|analysis|translate|rewrite|compare|contrast|differences?|similarities?|"
    r"full document|whole document|entire document|entire file|whole file|full file|"
    r"this document|this file|that document|that file|from start to finish|main takeaways|key points"
    r")\b",
    re.IGNORECASE,
)
MULTI_DOCUMENT_HINT_PATTERN = re.compile(
    r"\b(compare|contrast|differences?|similarities?|all documents|all files|uploaded documents|uploaded files)\b",
    re.IGNORECASE,
)
MAX_SUB_AGENT_DOCUMENTS = 3
MAX_SUB_AGENT_KEY_POINTS = 5
MAX_SUB_AGENT_EVIDENCE_SNIPPETS = 3
MAX_DOCUMENT_SOURCE_CHARS = 18000


class SubAgentPayload(BaseModel):
    reasoning_summary: str = Field(default="")
    answer: str = Field(default="")
    key_points: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class SubAgentTarget:
    document: Document
    selection_reason: str


@dataclass(slots=True)
class SubAgentAnalysis:
    document: Document
    selection_reason: str
    reasoning_summary: str
    answer: str
    key_points: list[str]
    evidence_snippets: list[str]
    source_char_count: int
    source_was_truncated: bool


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def trim_text(value: str | None, *, max_length: int) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    return cleaned[:max_length].strip()


def normalize_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def looks_like_full_document_request(question: str) -> bool:
    normalized = " ".join(question.lower().split())
    return bool(FULL_DOCUMENT_HINT_PATTERN.search(normalized))


def targets_multiple_documents(question: str) -> bool:
    normalized = " ".join(question.lower().split())
    return bool(MULTI_DOCUMENT_HINT_PATTERN.search(normalized))


def build_document_aliases(document: Document) -> list[str]:
    aliases = {
        normalize_match_text(document.filename),
        normalize_match_text(Path(document.filename).stem),
    }
    return [alias for alias in aliases if len(alias) >= 3]


def dedupe_targets(items: list[SubAgentTarget], *, limit: int) -> list[SubAgentTarget]:
    deduped: list[SubAgentTarget] = []
    seen_ids: set[UUID] = set()
    for item in items:
        if item.document.id in seen_ids:
            continue
        deduped.append(item)
        seen_ids.add(item.document.id)
        if len(deduped) >= limit:
            break
    return deduped


def select_sub_agent_targets(
    db: Session,
    user_id: UUID,
    question: str,
    retrieved_chunks: list[RetrievedChunk],
) -> list[SubAgentTarget]:
    if not looks_like_full_document_request(question):
        return []

    completed_documents = list(
        db.scalars(
            select(Document)
            .where(visible_document_clause(user_id), Document.status == "completed")
            .order_by(Document.updated_at.desc())
        )
    )
    if not completed_documents:
        return []

    requested_limit = MAX_SUB_AGENT_DOCUMENTS if targets_multiple_documents(question) else 1
    normalized_question = normalize_match_text(question)

    explicit_targets = [
        SubAgentTarget(document=document, selection_reason="explicit filename match in the request")
        for document in completed_documents
        if any(alias in normalized_question for alias in build_document_aliases(document))
    ]
    retrieved_targets = [
        SubAgentTarget(document=item.document, selection_reason="top hybrid retrieval hit for the request")
        for item in retrieved_chunks
    ]

    targets = dedupe_targets(explicit_targets + retrieved_targets, limit=requested_limit)
    if targets:
        return targets

    if len(completed_documents) == 1:
        return [SubAgentTarget(document=completed_documents[0], selection_reason="only completed document in the workspace")]

    if targets_multiple_documents(question):
        fallback_targets = [
            SubAgentTarget(document=document, selection_reason="recent completed document used for cross-document analysis")
            for document in completed_documents[:requested_limit]
        ]
        return dedupe_targets(fallback_targets, limit=requested_limit)

    return [SubAgentTarget(document=completed_documents[0], selection_reason="most recently updated completed document")]


def load_document_text(db: Session, document_id: UUID) -> str:
    document = db.get(Document, document_id)
    if document and document.full_markdown:
        return document.full_markdown

    statement = (
        select(DocumentChunk.content)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    rows = list(db.execute(statement).scalars())
    return "\n\n".join(rows)


def build_document_source_text(content: str, *, max_chars: int = MAX_DOCUMENT_SOURCE_CHARS) -> tuple[str, bool]:
    cleaned = normalize_text(content)
    if len(cleaned) <= max_chars:
        return cleaned, False

    segment_length = max(max_chars // 4, 1)
    span = len(cleaned)
    anchors = [
        0,
        max((span // 4) - (segment_length // 2), 0),
        max((span // 2) - (segment_length // 2), 0),
        max(span - segment_length, 0),
    ]
    labels = ["START", "EARLY", "MIDDLE", "END"]
    sections: list[str] = []
    seen_slices: set[tuple[int, int]] = set()

    for label, anchor in zip(labels, anchors, strict=False):
        start = min(anchor, max(span - segment_length, 0))
        end = min(start + segment_length, span)
        key = (start, end)
        if key in seen_slices:
            continue
        section = cleaned[start:end].strip()
        if not section:
            continue
        sections.append(f"[{label}]\n{section}")
        seen_slices.add(key)

    return "\n\n".join(sections), True


def build_sub_agent_messages(
    *,
    question: str,
    document: Document,
    document_text: str,
    document_metadata_text: str,
    was_truncated: bool,
    redaction_active: bool = False,
) -> list[dict[str, str]]:
    truncation_note = (
        "The provided source covers representative sections from a long document, so mention uncertainty if your answer depends on omitted parts."
        if was_truncated
        else "You have the full document content that was indexed for this file."
    )
    system_prompt = (
        "You are a document-analysis sub-agent inside a larger RAG system. "
        "You receive exactly one document and one user question. "
        "Work only from the supplied document. "
        "Return a JSON object with keys reasoning_summary, answer, key_points, and evidence_snippets. "
        "reasoning_summary must be a short visible rationale, not private chain-of-thought. "
        "Keep key_points and evidence_snippets concise. "
        "If the document is insufficient, say so clearly."
    )
    if redaction_active:
        system_prompt += (
            " Some content may contain anonymized surrogate values. "
            "If you mention names, emails, phone numbers, locations, dates, or URLs from the source, "
            "reproduce them exactly as shown."
        )
    user_prompt = (
        f"User question:\n{question}\n\n"
        f"Document filename: {document.filename}\n"
        f"Document metadata: {document_metadata_text}\n"
        f"Scope note: {truncation_note}\n\n"
        "Document content:\n"
        f"{document_text}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def request_sub_agent_payload(messages: list[dict[str, str]]) -> SubAgentPayload:
    request_kwargs = {
        "model": settings.llm_chat_model,
        "messages": messages,
        "temperature": 0.1,
    }
    try:
        response = sub_agent_client.chat.completions.create(
            **request_kwargs,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = sub_agent_client.chat.completions.create(**request_kwargs)

    if not response.choices:
        raise ValueError("Sub-agent returned no choices")

    raw_text = get_completion_text(response.choices[0].message.content)
    try:
        payload = json.loads(extract_json_object(raw_text))
        return SubAgentPayload.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError):
        fallback_answer = trim_text(raw_text, max_length=2400)
        return SubAgentPayload(
            reasoning_summary="Reviewed the delegated document in isolated context.",
            answer=fallback_answer or "The delegated analysis did not return a usable answer.",
            key_points=[],
            evidence_snippets=[],
        )


@traceable(name="document-sub-agent", run_type="chain")
def run_document_sub_agent(
    db: Session,
    *,
    question: str,
    target: SubAgentTarget,
    redaction_session: ConversationRedactionSession | None = None,
) -> SubAgentAnalysis:
    full_text = load_document_text(db, target.document.id)
    if not full_text.strip():
        return SubAgentAnalysis(
            document=target.document,
            selection_reason=target.selection_reason,
            reasoning_summary="The delegated document had no indexed text available.",
            answer="I could not analyze that document because it has no indexed text.",
            key_points=[],
            evidence_snippets=[],
            source_char_count=0,
            source_was_truncated=False,
        )

    source_text, was_truncated = build_document_source_text(full_text)
    metadata_text = json.dumps(target.document.extracted_metadata or {}, default=str)
    if redaction_session and redaction_session.has_active_redaction():
        question = redaction_session.anonymize_text(question)
        source_text = redaction_session.anonymize_text(source_text)
        metadata_text = redaction_session.anonymize_text(metadata_text)
    payload = request_sub_agent_payload(
        build_sub_agent_messages(
            question=question,
            document=target.document,
            document_text=source_text,
            document_metadata_text=metadata_text,
            was_truncated=was_truncated,
            redaction_active=bool(redaction_session and redaction_session.has_active_redaction()),
        )
    )
    if redaction_session and redaction_session.has_active_redaction():
        payload.reasoning_summary = redaction_session.deanonymize_text(payload.reasoning_summary)
        payload.answer = redaction_session.deanonymize_text(payload.answer)
        payload.key_points = [redaction_session.deanonymize_text(item) for item in payload.key_points]
        payload.evidence_snippets = [redaction_session.deanonymize_text(item) for item in payload.evidence_snippets]
    return SubAgentAnalysis(
        document=target.document,
        selection_reason=target.selection_reason,
        reasoning_summary=trim_text(payload.reasoning_summary, max_length=240),
        answer=trim_text(payload.answer, max_length=2400),
        key_points=[trim_text(item, max_length=220) for item in payload.key_points if clean_text(item)][
            :MAX_SUB_AGENT_KEY_POINTS
        ],
        evidence_snippets=[trim_text(item, max_length=220) for item in payload.evidence_snippets if clean_text(item)][
            :MAX_SUB_AGENT_EVIDENCE_SNIPPETS
        ],
        source_char_count=len(source_text),
        source_was_truncated=was_truncated,
    )
