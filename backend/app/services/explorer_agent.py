from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.models import Document
from app.services.folders import visible_document_clause
from app.services.knowledge_base import (
    execute_glob,
    execute_grep,
    execute_ls,
    execute_read,
    execute_tree,
    looks_like_explorer_request,
)
from app.services.metadata import extract_json_object, get_completion_text
from app.services.redaction import ConversationRedactionSession
from app.services.sub_agents import SubAgentAnalysis, SubAgentTarget, run_document_sub_agent
from app.services.tracing import traceable


explorer_client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
MAX_EXPLORER_TOOL_ROUNDS = 6
MAX_EXPLORER_ANALYSES = 3
PATH_PATTERN = re.compile(r"(/(?:global|private)(?:/[A-Za-z0-9._ -]+)*)", re.IGNORECASE)
QUOTED_TEXT_PATTERN = re.compile(r'"([^"]+)"')


EXPLORER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List folders and files inside a knowledge-base path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path like /global/reports or /private"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tree",
            "description": "Show a hierarchical tree for a knowledge-base path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 6},
                    "limit": {"type": "integer", "minimum": 10, "maximum": 200},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Regex-search extracted document content and return matching documents",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Match document filenames and paths with glob patterns like *.pdf or reports/**/*.md",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read the full extracted text for a document or a specific line range",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["document_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_document",
            "description": "Run the deep document-analysis sub-agent after locating a relevant document",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                },
                "required": ["document_id"],
            },
        },
    },
]


class ExplorerPayload(BaseModel):
    reasoning_summary: str = Field(default="")
    answer: str = Field(default="")
    findings: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class ExplorerToolEvent:
    tool_name: str
    input_summary: str
    output_summary: str


@dataclass(slots=True)
class ExplorerResult:
    reasoning_summary: str
    answer: str
    findings: list[str] = field(default_factory=list)
    analyses: list[SubAgentAnalysis] = field(default_factory=list)
    tool_events: list[ExplorerToolEvent] = field(default_factory=list)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


def _summarize_tool_output(output: Any, *, max_length: int = 240) -> str:
    serialized = _json_dumps(output)
    return serialized if len(serialized) <= max_length else f"{serialized[:max_length].rstrip()}..."


def _transform_jsonable_strings(value: Any, transform) -> Any:
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, list):
        return [_transform_jsonable_strings(item, transform) for item in value]
    if isinstance(value, dict):
        return {key: _transform_jsonable_strings(item, transform) for key, item in value.items()}
    return value


def _resolve_visible_document(db: Session, user_id: UUID | str, document_id: UUID | str) -> Document:
    statement = (
        select(Document)
        .options(selectinload(Document.folder))
        .where(Document.id == document_id, visible_document_clause(user_id), Document.status == "completed")
    )
    document = db.scalar(statement)
    if document is None:
        raise ValueError("Document not found")
    return document


def _run_analyze_tool(
    db: Session,
    *,
    user_id: UUID | str,
    question: str,
    document_id: UUID | str,
    redaction_session: ConversationRedactionSession | None = None,
) -> tuple[SubAgentAnalysis, dict[str, Any]]:
    document = _resolve_visible_document(db, user_id, document_id)
    analysis = run_document_sub_agent(
        db,
        question=question,
        target=SubAgentTarget(document=document, selection_reason="knowledge-base explorer located a likely source"),
        redaction_session=redaction_session,
    )
    output = {
        "documentId": str(document.id),
        "filename": document.filename,
        "reasoningSummary": analysis.reasoning_summary,
        "answer": analysis.answer,
        "keyPoints": analysis.key_points,
    }
    return analysis, output


def _fallback_pattern(question: str) -> str:
    quoted = QUOTED_TEXT_PATTERN.search(question)
    if quoted:
        return re.escape(quoted.group(1))

    keywords = [token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", question) if token.lower() not in {"global", "private", "folder", "folders", "file", "files"}]
    if not keywords:
        return ".*"
    selected = keywords[:4]
    return "|".join(re.escape(token) for token in selected)


def _fallback_glob(question: str) -> str | None:
    for token in re.findall(r"[A-Za-z0-9_./*\-?\[\]]+", question):
        if "*" in token or "?" in token or "[" in token:
            return token
    return None


def _fallback_path(question: str) -> str | None:
    match = PATH_PATTERN.search(question)
    if not match:
        return None
    return match.group(1)


def _build_fallback_result(
    db: Session,
    *,
    user_id: UUID | str,
    question: str,
    redaction_session: ConversationRedactionSession | None = None,
) -> ExplorerResult:
    tool_events: list[ExplorerToolEvent] = []
    analyses: list[SubAgentAnalysis] = []
    findings: list[str] = []
    explicit_path = _fallback_path(question)

    if any(term in question.lower() for term in ("tree", "structure", "folders", "under", "inside")):
        output = execute_tree(db, user_id, explicit_path or "/", depth=3, limit=60)
        tool_events.append(
            ExplorerToolEvent(
                tool_name="tree",
                input_summary=explicit_path or "/",
                output_summary=_summarize_tool_output({"path": output["path"], "truncated": output["truncated"]}),
            )
        )
        findings.append(output["output"] or "No visible entries.")
        return ExplorerResult(
            reasoning_summary="Used the knowledge-base tree view to inspect the visible structure.",
            answer=output["output"] or "No visible folders or files were found for that path.",
            findings=findings,
            analyses=analyses,
            tool_events=tool_events,
        )

    glob_pattern = _fallback_glob(question)
    if glob_pattern:
        output = execute_glob(db, user_id, glob_pattern, limit=8)
        tool_events.append(
            ExplorerToolEvent(
                tool_name="glob",
                input_summary=glob_pattern,
                output_summary=_summarize_tool_output({"matches": len(output["matches"])}),
            )
        )
        findings.extend(match["path"] for match in output["matches"][:5])
        return ExplorerResult(
            reasoning_summary="Matched document paths with a glob pattern in the visible knowledge base.",
            answer="\n".join(findings) if findings else "No documents matched that pattern.",
            findings=findings,
            analyses=analyses,
            tool_events=tool_events,
        )

    grep_output = execute_grep(db, user_id, _fallback_pattern(question), explicit_path, limit=5)
    tool_events.append(
        ExplorerToolEvent(
            tool_name="grep",
            input_summary=_fallback_pattern(question),
            output_summary=_summarize_tool_output({"matches": len(grep_output["matches"])}),
        )
    )
    for match in grep_output["matches"][:MAX_EXPLORER_ANALYSES]:
        analysis, analysis_output = _run_analyze_tool(
            db,
            user_id=user_id,
            question=question,
            document_id=match["documentId"],
            redaction_session=redaction_session,
        )
        analyses.append(analysis)
        tool_events.append(
            ExplorerToolEvent(
                tool_name="analyze_document",
                input_summary=match["documentId"],
                output_summary=_summarize_tool_output(analysis_output),
            )
        )
        findings.append(f"{analysis.document.filename}: {analysis.reasoning_summary or analysis.answer}")

    answer = "\n".join(findings) if findings else "The explorer did not find a matching document in the visible knowledge base."
    return ExplorerResult(
        reasoning_summary="Used fallback knowledge-base search because the model did not complete a tool-driven exploration loop.",
        answer=answer,
        findings=findings,
        analyses=analyses,
        tool_events=tool_events,
    )


@traceable(name="knowledge-base-explorer", run_type="chain")
def run_explorer_sub_agent(
    db: Session,
    *,
    user_id: UUID | str,
    question: str,
    redaction_session: ConversationRedactionSession | None = None,
) -> ExplorerResult:
    if not looks_like_explorer_request(question):
        return ExplorerResult(reasoning_summary="", answer="", findings=[], analyses=[], tool_events=[])

    system_prompt = (
        "You are a knowledge-base explorer sub-agent inside a larger RAG system. "
        "Use the available filesystem-like tools to inspect the knowledge base before answering. "
        "Prefer ls, tree, grep, glob, and read to locate evidence. "
        "Use analyze_document when you need a deeper synthesis from a specific file. "
        "Return a JSON object with reasoning_summary, answer, and findings. "
        "reasoning_summary must be a short visible explanation, not private chain-of-thought."
    )
    if redaction_session and redaction_session.has_active_redaction():
        system_prompt += (
            " Some content may contain anonymized surrogate values. "
            "Reproduce names, emails, phone numbers, locations, dates, and URLs exactly as they appear in the tool output."
        )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": redaction_session.anonymize_text(question)
            if redaction_session and redaction_session.has_active_redaction()
            else question,
        },
    ]
    tool_events: list[ExplorerToolEvent] = []
    analyses_by_id: dict[str, SubAgentAnalysis] = {}

    try:
        for _ in range(MAX_EXPLORER_TOOL_ROUNDS):
            response = explorer_client.chat.completions.create(
                model=settings.llm_chat_model,
                messages=messages,
                tools=EXPLORER_TOOLS,
                tool_choice="auto",
                temperature=0.1,
            )
            if not response.choices:
                break

            assistant_message = response.choices[0].message
            tool_calls = assistant_message.tool_calls or []
            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_message.content or "",
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": tool_call.type,
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments,
                                },
                            }
                            for tool_call in tool_calls
                        ],
                    }
                )

                for tool_call in tool_calls:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                    execution_arguments = (
                        _transform_jsonable_strings(arguments, redaction_session.deanonymize_text)
                        if redaction_session and redaction_session.has_active_redaction()
                        else arguments
                    )
                    tool_name = tool_call.function.name
                    analysis: SubAgentAnalysis | None = None

                    if tool_name == "ls":
                        output = execute_ls(db, user_id, execution_arguments.get("path"))
                    elif tool_name == "tree":
                        output = execute_tree(
                            db,
                            user_id,
                            execution_arguments.get("path"),
                            depth=int(execution_arguments.get("depth", 3)),
                            limit=int(execution_arguments.get("limit", 80)),
                        )
                    elif tool_name == "grep":
                        output = execute_grep(
                            db,
                            user_id,
                            execution_arguments["pattern"],
                            execution_arguments.get("path"),
                            limit=int(execution_arguments.get("limit", 20)),
                        )
                    elif tool_name == "glob":
                        output = execute_glob(
                            db,
                            user_id,
                            execution_arguments["pattern"],
                            limit=int(execution_arguments.get("limit", 20)),
                        )
                    elif tool_name == "read":
                        output = execute_read(
                            db,
                            user_id,
                            execution_arguments["document_id"],
                            start_line=execution_arguments.get("start_line"),
                            end_line=execution_arguments.get("end_line"),
                        )
                    elif tool_name == "analyze_document":
                        analysis, output = _run_analyze_tool(
                            db,
                            user_id=user_id,
                            question=question,
                            document_id=execution_arguments["document_id"],
                            redaction_session=redaction_session,
                        )
                    else:
                        output = {"error": f"Unknown tool: {tool_name}"}

                    if analysis is not None:
                        analyses_by_id[str(analysis.document.id)] = analysis

                    tool_events.append(
                        ExplorerToolEvent(
                            tool_name=tool_name,
                            input_summary=_summarize_tool_output(arguments, max_length=120),
                            output_summary=_summarize_tool_output(output),
                        )
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": _json_dumps(
                                redaction_session.anonymize_jsonable(output)
                                if redaction_session and redaction_session.has_active_redaction()
                                else output
                            ),
                        }
                    )
                continue

            raw_text = get_completion_text(assistant_message.content)
            try:
                payload = ExplorerPayload.model_validate(json.loads(extract_json_object(raw_text)))
            except (json.JSONDecodeError, ValidationError, ValueError):
                payload = ExplorerPayload(
                    reasoning_summary="Completed a tool-driven knowledge-base exploration run.",
                    answer=raw_text.strip() or "The explorer completed but did not return a structured summary.",
                    findings=[],
                )
            if redaction_session and redaction_session.has_active_redaction():
                payload.reasoning_summary = redaction_session.deanonymize_text(payload.reasoning_summary)
                payload.answer = redaction_session.deanonymize_text(payload.answer)
                payload.findings = [redaction_session.deanonymize_text(item) for item in payload.findings]
            return ExplorerResult(
                reasoning_summary=payload.reasoning_summary,
                answer=payload.answer,
                findings=payload.findings,
                analyses=list(analyses_by_id.values())[:MAX_EXPLORER_ANALYSES],
                tool_events=tool_events,
            )
    except Exception:
        return _build_fallback_result(db, user_id=user_id, question=question, redaction_session=redaction_session)

    return _build_fallback_result(db, user_id=user_id, question=question, redaction_session=redaction_session)
