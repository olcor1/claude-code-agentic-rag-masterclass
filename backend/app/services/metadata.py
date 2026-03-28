import json
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.services.local_llm import get_local_llm_client, get_local_llm_model
from app.services.tracing import traceable
from app.utils.text import normalize_text


METADATA_SCHEMA_VERSION = 1
MAX_METADATA_SOURCE_CHARS = 6000
MAX_METADATA_LIST_ITEMS = 6

metadata_client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


class ExtractedDocumentMetadata(BaseModel):
    title: str | None = None
    summary: str | None = None
    document_type: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    language: str | None = None


def normalize_filter_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).strip().split()).lower()
    return cleaned or None


def normalize_filter_values(values: list[str] | None, *, limit: int | None = None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        cleaned = normalize_filter_value(value)
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
        if limit is not None and len(normalized) >= limit:
            break
    return normalized


def trim_text(value: str | None, *, max_length: int) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    return cleaned[:max_length].strip()


def serialize_metadata(metadata: ExtractedDocumentMetadata) -> dict[str, Any]:
    return {
        "title": trim_text(metadata.title, max_length=160),
        "summary": trim_text(metadata.summary, max_length=400),
        "document_type": normalize_filter_value(metadata.document_type),
        "topics": normalize_filter_values(metadata.topics, limit=MAX_METADATA_LIST_ITEMS),
        "entities": normalize_filter_values(metadata.entities, limit=MAX_METADATA_LIST_ITEMS),
        "language": normalize_filter_value(metadata.language),
    }


def build_metadata_source_text(content: str, *, max_chars: int = MAX_METADATA_SOURCE_CHARS) -> str:
    cleaned = normalize_text(content)
    if len(cleaned) <= max_chars:
        return cleaned

    segment_length = max(max_chars // 3, 1)
    middle_start = max((len(cleaned) // 2) - (segment_length // 2), 0)
    sections = [
        ("START", cleaned[:segment_length]),
        ("MIDDLE", cleaned[middle_start : middle_start + segment_length]),
        ("END", cleaned[-segment_length:]),
    ]
    return "\n\n".join(f"[{label}]\n{section}".strip() for label, section in sections if section)


def extract_json_object(raw_text: str) -> str:
    candidate = raw_text.strip()
    if candidate.startswith("```"):
        fence_lines = [line for line in candidate.splitlines() if not line.strip().startswith("```")]
        candidate = "\n".join(fence_lines).strip()

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return candidate
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    if start == -1:
        raise ValueError("Metadata extraction did not return a JSON object")

    depth = 0
    for index in range(start, len(candidate)):
        character = candidate[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return candidate[start : index + 1]

    raise ValueError("Metadata extraction returned malformed JSON")


def get_completion_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text_value = getattr(item, "text", None)
            if text_value:
                parts.append(text_value)
        return "\n".join(parts)
    return ""


def request_metadata_completion(messages: list[dict[str, str]]) -> str:
    local_client = get_local_llm_client()
    local_model = get_local_llm_model()
    client = local_client or metadata_client
    model = local_model or settings.resolved_llm_metadata_model
    request_kwargs = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }
    try:
        response = client.chat.completions.create(
            **request_kwargs,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = client.chat.completions.create(**request_kwargs)

    if not response.choices:
        raise ValueError("Metadata extraction returned no choices")

    return get_completion_text(response.choices[0].message.content)


@traceable(name="extract-document-metadata", run_type="llm")
def extract_document_metadata(filename: str, content: str) -> dict[str, Any]:
    source_text = build_metadata_source_text(content)
    system_prompt = (
        "Extract structured metadata from the supplied document. "
        "Return a JSON object with exactly these keys: "
        "title, summary, document_type, topics, entities, language. "
        "Use concise values. "
        "Return lowercase values for document_type, topics, entities, and language. "
        "Use arrays for topics and entities. "
        "If a field is unknown, use null for strings and [] for arrays."
    )
    user_prompt = (
        f"Filename: {filename}\n\n"
        "Document content sample:\n"
        f"{source_text}"
    )
    raw_text = request_metadata_completion(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    try:
        payload = json.loads(extract_json_object(raw_text))
    except json.JSONDecodeError as exc:  # pragma: no cover - provider-specific failure path
        raise ValueError("Metadata extraction returned invalid JSON") from exc

    try:
        metadata = ExtractedDocumentMetadata.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("Metadata extraction returned an unexpected schema") from exc

    return serialize_metadata(metadata)
