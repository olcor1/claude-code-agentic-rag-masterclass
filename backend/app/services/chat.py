import json
import re
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.models import Conversation, Message
from app.db.session import SessionLocal, bind_current_user_context
from app.services.agent_trace import (
    add_agent_reasoning,
    add_agent_step,
    add_child_agent,
    complete_agent,
    create_agent_trace,
    fail_agent,
    set_agent_summary,
    update_agent_step,
)
from app.services.retrieval import RetrievedChunk, retrieve_relevant_chunks
from app.services.sub_agents import (
    SubAgentAnalysis,
    looks_like_full_document_request,
    run_document_sub_agent,
    select_sub_agent_targets,
)
from app.services.tracing import traceable
from app.services.web_search import WebSearchResult, search_web
from app.services.workspace_sql import WorkspaceSQLResult, run_workspace_sql


client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
WORKSPACE_SQL_ANALYTICS_PATTERN = re.compile(
    r"\b("
    r"how many|count|number of|total|average|avg|top|most|least|list|show|which|"
    r"breakdown|group by|per |latest|newest|oldest|status|version|uploaded"
    r")\b",
    re.IGNORECASE,
)
WORKSPACE_SQL_NOUNS = (
    "document",
    "documents",
    "doc",
    "docs",
    "file",
    "files",
    "topic",
    "topics",
    "entity",
    "entities",
    "language",
    "languages",
    "conversation",
    "conversations",
    "thread",
    "threads",
    "chat",
    "chats",
    "message",
    "messages",
    "citation",
    "citations",
    "upload",
    "uploads",
    "workspace",
    "knowledge base",
)
WEB_SEARCH_HINTS = (
    "search the web",
    "search online",
    "internet",
    "online",
    "web search",
)
CURRENT_INFO_HINTS = (
    "today",
    "current",
    "latest",
    "recent",
    "news",
    "weather",
    "stock",
    "price",
    "release",
    "announcement",
)


def truncate_text(value: str, max_length: int = 320) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[:max_length].rstrip()}..."


def create_conversation(db: Session, user_id: UUID, title: str | None = None) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title or "New conversation")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def list_conversations(db: Session, user_id: UUID) -> list[Conversation]:
    statement = select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc())
    return list(db.scalars(statement))


def get_conversation_or_404(db: Session, conversation_id: UUID | str, user_id: UUID | str) -> Conversation:
    statement = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    conversation = db.scalar(statement)
    if not conversation:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


def looks_like_workspace_question(content: str) -> bool:
    lowered = " ".join(content.lower().split())
    return any(term in lowered for term in WORKSPACE_SQL_NOUNS)


def should_run_workspace_sql(content: str) -> bool:
    lowered = " ".join(content.lower().split())
    if not looks_like_workspace_question(lowered):
        return False
    if WORKSPACE_SQL_ANALYTICS_PATTERN.search(lowered):
        return True
    return bool(re.search(r"\bwhat\b.*\b(documents|docs|files|topics|entities|languages|conversations|threads|messages)\b", lowered))


def should_run_web_search(
    content: str,
    *,
    retrieved_chunks: list[RetrievedChunk],
    sql_result: WorkspaceSQLResult | None,
    sub_agent_results: list[SubAgentAnalysis],
) -> bool:
    if not settings.web_search_enabled:
        return False

    lowered = " ".join(content.lower().split())
    if any(term in lowered for term in WEB_SEARCH_HINTS):
        return True
    if any(term in lowered for term in CURRENT_INFO_HINTS) and not looks_like_workspace_question(lowered):
        return True
    if retrieved_chunks or sql_result or sub_agent_results:
        return False
    if looks_like_workspace_question(lowered):
        return False
    return True


def describe_filter_scope(metadata_filters: dict[str, Any] | None) -> str:
    if not metadata_filters:
        return "User question only."

    active_parts = [
        f"{key}: {', '.join(str(item) for item in values)}"
        for key, values in metadata_filters.items()
        if isinstance(values, list) and values
    ]
    if not active_parts:
        return "User question only."
    return f"User question plus metadata filters ({'; '.join(active_parts)})."


def describe_main_agent_summary(
    retrieved_chunks: list[RetrievedChunk],
    sub_agent_results: list[SubAgentAnalysis],
    sql_result: WorkspaceSQLResult | None,
    web_results: list[WebSearchResult],
) -> str:
    evidence_parts: list[str] = []
    if retrieved_chunks:
        evidence_parts.append(f"{len(retrieved_chunks)} retrieved chunk(s)")
    if sub_agent_results:
        evidence_parts.append(f"{len(sub_agent_results)} full-document sub-agent run(s)")
    if sql_result:
        evidence_parts.append("workspace SQL")
    if web_results:
        evidence_parts.append(f"{len(web_results)} web fallback result(s)")
    if not evidence_parts:
        return "Answered with limited evidence and no grounded workspace matches."
    if len(evidence_parts) == 1:
        return f"Answered using {evidence_parts[0]}."
    return f"Answered using {', '.join(evidence_parts[:-1])}, and {evidence_parts[-1]}."


def build_document_context_sections(
    retrieved_chunks: list[RetrievedChunk],
    sub_agent_results: list[SubAgentAnalysis],
) -> tuple[list[str], list[dict[str, Any]]]:
    sections: list[str] = []
    citations: list[dict[str, Any]] = []
    index = 1

    for item in retrieved_chunks:
        method_label = ", ".join(item.retrieval_methods)
        sections.append(f"[{index}] {item.document.filename} ({method_label})\n{item.chunk.content}")
        citations.append(
            {
                "index": index,
                "sourceType": "document",
                "chunkId": str(item.chunk.id),
                "documentId": str(item.document.id),
                "filename": item.document.filename,
                "excerpt": truncate_text(item.chunk.content, 180),
                "matchType": item.match_type,
                "retrievalMethods": item.retrieval_methods,
                "vectorDistance": item.vector_distance,
                "keywordScore": item.keyword_score,
                "rrfScore": item.rrf_score,
                "rerankScore": item.rerank_score,
            }
        )
        index += 1

    for item in sub_agent_results:
        section_lines = [
            f"[{index}] Full-document analysis for {item.document.filename}",
            f"Selection reason: {item.selection_reason}",
            f"Reasoning summary: {item.reasoning_summary}",
            f"Analysis: {item.answer}",
        ]
        if item.key_points:
            section_lines.append("Key points:\n" + "\n".join(f"- {point}" for point in item.key_points))
        if item.evidence_snippets:
            section_lines.append("Evidence snippets:\n" + "\n".join(f"- {snippet}" for snippet in item.evidence_snippets))
        if item.source_was_truncated:
            section_lines.append("Note: the delegated source used representative document sections because the indexed text was long.")
        sections.append("\n".join(section_lines))
        citations.append(
            {
                "index": index,
                "sourceType": "document",
                "documentId": str(item.document.id),
                "filename": item.document.filename,
                "excerpt": truncate_text(item.answer or item.reasoning_summary, 220),
                "matchType": "full_document",
                "label": "Full document analysis",
            }
        )
        index += 1

    return sections, citations


def build_sql_citations(sql_result: WorkspaceSQLResult | None) -> list[dict[str, Any]]:
    if not sql_result:
        return []

    return [
        {
            "index": 1,
            "sourceType": "sql",
            "label": "Workspace SQL",
            "excerpt": truncate_text(sql_result.preview_text(), 420),
            "query": sql_result.sql,
            "rowCount": sql_result.row_count,
            "columns": sql_result.columns,
        }
    ]


def build_web_citations(web_results: list[WebSearchResult]) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "sourceType": "web",
            "title": item.title,
            "url": item.url,
            "domain": item.domain,
            "excerpt": truncate_text(item.snippet or item.title, 240),
        }
        for index, item in enumerate(web_results, start=1)
    ]


def build_prompt(
    content: str,
    history: list[Message],
    document_sections: list[str],
    sql_result: WorkspaceSQLResult | None = None,
    web_results: list[WebSearchResult] | None = None,
    web_search_status: str | None = None,
) -> list[dict[str, str]]:
    system_prompt = (
        "You are a grounded assistant for a local RAG workspace. "
        "Prefer knowledge-base evidence when it answers the question, and cite it like [1] or [2]. "
        "Use structured workspace SQL evidence when the answer depends on document, conversation, or message metadata, and cite it like [SQL1]. "
        "Use web-search evidence only when the workspace is insufficient, and cite it like [WEB1]. "
        "Do not invent citations or claim certainty without evidence. "
        "If the available evidence is insufficient, say so clearly."
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for message in history[-8:]:
        messages.append({"role": message.role, "content": message.content})

    user_prompt = "Knowledge base context:\n"
    user_prompt += "\n\n".join(document_sections) if document_sections else "No retrieved knowledge-base context."

    user_prompt += "\n\nWorkspace SQL results:\n"
    if sql_result:
        user_prompt += (
            "[SQL1] Workspace analytics query\n"
            f"SQL: {sql_result.sql}\n"
            f"Rows: {sql_result.preview_text()}"
        )
    else:
        user_prompt += "No workspace SQL results."

    user_prompt += "\n\nWeb search results:\n"
    if web_results:
        user_prompt += "\n\n".join(
            [
                (
                    f"[WEB{index}] {item.title}\n"
                    f"URL: {item.url}\n"
                    f"Snippet: {item.snippet or 'No snippet provided.'}"
                )
                for index, item in enumerate(web_results, start=1)
            ]
        )
    else:
        user_prompt += web_search_status or "No web results."

    user_prompt += f"\n\nUser question:\n{content}"
    messages.append({"role": "user", "content": user_prompt})
    return messages


def format_sse(event: str, data: str) -> str:
    safe_data = data.replace("\r", "")
    return f"event: {event}\ndata: {safe_data}\n\n"


def format_trace_sse(agent_trace: dict[str, Any]) -> str:
    return format_sse("trace", json.dumps({"agentTrace": agent_trace}))


@traceable(name="stream-chat-response", run_type="llm")
def stream_conversation_reply(
    conversation_id: str,
    user_id: str,
    content: str,
    metadata_filters: dict[str, Any] | None = None,
) -> Generator[str, None, None]:
    with SessionLocal() as db:
        bind_current_user_context(db, user_id)
        conversation = get_conversation_or_404(db, UUID(conversation_id), UUID(user_id))
        history = sorted(conversation.messages, key=lambda item: item.created_at)

        user_message = Message(conversation_id=conversation.id, role="user", content=content, citations=[], agent_trace={})
        db.add(user_message)
        if len(history) == 0:
            conversation.title = content[:60] or "New conversation"
        conversation.updated_at = datetime.now(UTC)
        db.commit()

        agent_trace = create_agent_trace(label="Main agent", kind="main", summary="Planning grounded response.")
        add_agent_reasoning(
            agent_trace,
            "Started with workspace retrieval so the response could stay grounded before falling back to other tools.",
        )
        yield format_trace_sse(agent_trace)

        yield format_sse("status", json.dumps({"text": "Running hybrid retrieval"}))
        retrieval_step = add_agent_step(
            agent_trace,
            title="Hybrid retrieval",
            kind="tool",
            tool_name="retrieve_relevant_chunks",
            summary="Searching indexed chunks for grounded evidence.",
            input_summary=describe_filter_scope(metadata_filters),
        )
        yield format_trace_sse(agent_trace)

        retrieved_chunks = retrieve_relevant_chunks(db, conversation.user_id, content, metadata_filters)
        unique_documents = len({item.document.id for item in retrieved_chunks})
        update_agent_step(
            retrieval_step,
            status="completed",
            summary=f"Retrieved {len(retrieved_chunks)} chunk(s) across {unique_documents} document(s).",
            output_summary="Hybrid retrieval merged keyword and vector candidates, then reranked them.",
        )
        if retrieved_chunks:
            add_agent_reasoning(
                agent_trace,
                f"Hybrid retrieval found chunk-level evidence in {unique_documents} document(s).",
            )
        else:
            add_agent_reasoning(
                agent_trace,
                "Hybrid retrieval did not find chunk-level evidence, so other tools may need to carry the answer.",
            )
        yield format_trace_sse(agent_trace)

        sql_result: WorkspaceSQLResult | None = None
        if should_run_workspace_sql(content):
            yield format_sse("status", json.dumps({"text": "Querying structured workspace data"}))
            sql_step = add_agent_step(
                agent_trace,
                title="Workspace SQL",
                kind="tool",
                tool_name="run_workspace_sql",
                summary="Checking whether the answer depends on structured workspace metadata.",
                input_summary="User question routed through workspace analytics heuristics.",
            )
            yield format_trace_sse(agent_trace)

            sql_result = run_workspace_sql(db, conversation.user_id, content)
            if sql_result:
                update_agent_step(
                    sql_step,
                    status="completed",
                    summary=f"Workspace SQL returned {sql_result.row_count} row(s).",
                    output_summary=sql_result.rationale or "Structured workspace query completed successfully.",
                )
                add_agent_reasoning(
                    agent_trace,
                    "The request looked partly structured, so I added workspace SQL results to complement document evidence.",
                )
            else:
                update_agent_step(
                    sql_step,
                    status="completed",
                    summary="Workspace SQL did not find a reliable structured answer.",
                    output_summary="The question was either unsupported by the structured snapshot or too ambiguous for safe SQL generation.",
                )
            yield format_trace_sse(agent_trace)

        sub_agent_results: list[SubAgentAnalysis] = []
        full_document_request = looks_like_full_document_request(content)
        sub_agent_targets = select_sub_agent_targets(db, conversation.user_id, content, retrieved_chunks)
        if sub_agent_targets:
            yield format_sse("status", json.dumps({"text": "Delegating full-document analysis"}))
            add_agent_reasoning(
                agent_trace,
                "The request looked like a full-document task, so I delegated scoped analysis to isolated sub-agents.",
            )
            delegation_step = add_agent_step(
                agent_trace,
                title="Sub-agent delegation",
                kind="delegation",
                tool_name="document_sub_agent",
                summary=f"Delegating {len(sub_agent_targets)} document-focused analysis run(s).",
                input_summary="Only matched or top-ranked completed documents were sent to the delegated agents.",
            )
            yield format_trace_sse(agent_trace)

            for target in sub_agent_targets:
                child_trace = create_agent_trace(
                    label=f"Sub-agent · {target.document.filename}",
                    kind="subagent",
                    summary="Preparing isolated full-document analysis.",
                )
                add_agent_reasoning(
                    child_trace,
                    f"Selected {target.document.filename} because it was {target.selection_reason}.",
                )
                add_child_agent(agent_trace, child_trace)
                child_step = add_agent_step(
                    child_trace,
                    title="Full-document analysis",
                    kind="tool",
                    tool_name="document_sub_agent",
                    summary="Reviewing delegated document context in isolation.",
                    input_summary=target.selection_reason,
                )
                yield format_trace_sse(agent_trace)

                try:
                    analysis = run_document_sub_agent(db, question=content, target=target)
                    sub_agent_results.append(analysis)
                    update_agent_step(
                        child_step,
                        status="completed",
                        summary=f"Analyzed {analysis.document.filename} using {analysis.source_char_count} characters of indexed context.",
                        output_summary=analysis.reasoning_summary or "Delegated analysis completed.",
                    )
                    add_agent_reasoning(child_trace, analysis.reasoning_summary or "Delegated analysis completed.")
                    complete_agent(
                        child_trace,
                        summary=f"Returned a scoped document analysis for {analysis.document.filename}.",
                    )
                except Exception as exc:  # pragma: no cover - provider-specific failure path
                    update_agent_step(
                        child_step,
                        status="failed",
                        summary=f"Delegated analysis failed for {target.document.filename}.",
                        output_summary=str(exc),
                    )
                    fail_agent(child_trace, f"Delegated analysis failed for {target.document.filename}.")

                yield format_trace_sse(agent_trace)

            if sub_agent_results:
                update_agent_step(
                    delegation_step,
                    status="completed",
                    summary=f"Completed {len(sub_agent_results)} sub-agent analysis run(s).",
                    output_summary="Delegated outputs were folded back into the main answer context.",
                )
            else:
                update_agent_step(
                    delegation_step,
                    status="completed",
                    summary="Delegation completed without a usable sub-agent result.",
                    output_summary="The main agent continued with chunk retrieval and other tools only.",
                )
            yield format_trace_sse(agent_trace)
        elif full_document_request:
            add_agent_reasoning(
                agent_trace,
                "The request looked like a full-document task, but there was no completed matching document to delegate.",
            )
            yield format_trace_sse(agent_trace)

        web_results: list[WebSearchResult] = []
        web_search_status = "No web search requested."
        if should_run_web_search(
            content,
            retrieved_chunks=retrieved_chunks,
            sql_result=sql_result,
            sub_agent_results=sub_agent_results,
        ):
            yield format_sse("status", json.dumps({"text": "Searching the web for fallback sources"}))
            web_step = add_agent_step(
                agent_trace,
                title="Web fallback",
                kind="tool",
                tool_name="search_web",
                summary="Checking the web because workspace evidence was insufficient or the request was explicitly current.",
            )
            yield format_trace_sse(agent_trace)

            web_search_response = search_web(content)
            web_results = web_search_response.results
            if web_results:
                web_search_status = f"Web fallback returned {len(web_results)} result(s)."
                update_agent_step(
                    web_step,
                    status="completed",
                    summary=f"Web fallback returned {len(web_results)} result(s).",
                    output_summary=web_search_response.provider or "Web search completed.",
                )
                add_agent_reasoning(
                    agent_trace,
                    "Workspace evidence was still thin, so I added web fallback sources for external grounding.",
                )
            elif web_search_response.error:
                web_search_status = f"Web search unavailable: {web_search_response.error}"
                update_agent_step(
                    web_step,
                    status="completed",
                    summary="Web fallback was unavailable.",
                    output_summary=web_search_response.error,
                )
            else:
                web_search_status = "Web search returned no matches."
                update_agent_step(
                    web_step,
                    status="completed",
                    summary="Web fallback returned no matches.",
                    output_summary=web_search_response.provider or "Web search completed with no results.",
                )
            yield format_trace_sse(agent_trace)
        elif not settings.web_search_enabled:
            web_search_status = "Web search fallback is disabled for this workspace."

        document_sections, document_citations = build_document_context_sections(retrieved_chunks, sub_agent_results)
        citations = document_citations + build_sql_citations(sql_result) + build_web_citations(web_results)
        yield format_sse("meta", json.dumps({"citations": citations}))

        synthesis_step = add_agent_step(
            agent_trace,
            title="Final synthesis",
            kind="tool",
            tool_name="chat_completion",
            summary="Drafting the final grounded response.",
            input_summary=describe_main_agent_summary(retrieved_chunks, sub_agent_results, sql_result, web_results),
        )
        set_agent_summary(
            agent_trace,
            describe_main_agent_summary(retrieved_chunks, sub_agent_results, sql_result, web_results),
        )
        yield format_trace_sse(agent_trace)

        if citations:
            yield format_sse("status", json.dumps({"text": "Streaming grounded answer"}))
        else:
            yield format_sse("status", json.dumps({"text": "Streaming answer with limited evidence"}))

        prompt = build_prompt(
            content,
            history,
            document_sections,
            sql_result=sql_result,
            web_results=web_results,
            web_search_status=web_search_status,
        )
        stream = client.chat.completions.create(
            model=settings.llm_chat_model,
            messages=prompt,
            temperature=0.2,
            stream=True,
        )

        output_parts: list[str] = []
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if not delta:
                continue
            output_parts.append(delta)
            yield format_sse("token", json.dumps({"text": delta}))

        assistant_content = "".join(output_parts).strip()
        update_agent_step(
            synthesis_step,
            status="completed",
            summary="Completed final response synthesis.",
            output_summary=f"Generated {len(assistant_content)} characters of answer text.",
        )
        complete_agent(
            agent_trace,
            summary=describe_main_agent_summary(retrieved_chunks, sub_agent_results, sql_result, web_results),
        )
        yield format_trace_sse(agent_trace)

        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_content,
            citations=citations,
            agent_trace=agent_trace,
        )
        db.add(assistant_message)
        conversation.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(assistant_message)

        payload = {
            "message": {
                "id": str(assistant_message.id),
                "conversationId": str(conversation.id),
                "role": assistant_message.role,
                "content": assistant_message.content,
                "citations": citations,
                "agentTrace": agent_trace,
                "createdAt": assistant_message.created_at.isoformat(),
            }
        }
        yield format_sse("done", json.dumps(payload))
