import json
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.models import Conversation, Document, DocumentChunk, Message
from app.db.session import SessionLocal
from app.services.embeddings import embed_texts
from app.services.tracing import traceable


client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


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


@traceable(name="retrieve-context", run_type="retriever")
def retrieve_relevant_chunks(db: Session, user_id: UUID, content: str) -> list[tuple[DocumentChunk, Document, float]]:
    [query_embedding] = embed_texts([content])
    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
    statement = (
        select(
            DocumentChunk,
            Document,
            distance,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.user_id == user_id, Document.status == "processed")
        .order_by(distance)
        .limit(settings.retrieval_limit)
    )
    return list(db.execute(statement).all())


def build_prompt(content: str, history: list[Message], retrieved_chunks: list[tuple[DocumentChunk, Document, float]]) -> list[dict]:
    context_sections: list[str] = []
    for index, (chunk, document, _) in enumerate(retrieved_chunks, start=1):
        context_sections.append(f"[{index}] {document.filename}\n{chunk.content}")

    system_prompt = (
        "You are a retrieval-augmented assistant. "
        "Answer using the provided context when possible and cite sources like [1] or [2]. "
        "If the context is insufficient, say so clearly."
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for message in history[-8:]:
        messages.append({"role": message.role, "content": message.content})

    user_prompt = "Context:\n"
    user_prompt += "\n\n".join(context_sections) if context_sections else "No retrieved context."
    user_prompt += f"\n\nUser question:\n{content}"
    messages.append({"role": "user", "content": user_prompt})
    return messages


def format_sse(event: str, data: str) -> str:
    safe_data = data.replace("\r", "")
    return f"event: {event}\ndata: {safe_data}\n\n"


@traceable(name="stream-chat-response", run_type="llm")
def stream_conversation_reply(conversation_id: str, user_id: str, content: str) -> Generator[str, None, None]:
    with SessionLocal() as db:
        conversation = get_conversation_or_404(db, UUID(conversation_id), UUID(user_id))
        history = sorted(conversation.messages, key=lambda item: item.created_at)

        user_message = Message(conversation_id=conversation.id, role="user", content=content, citations=[])
        db.add(user_message)
        if len(history) == 0:
            conversation.title = content[:60] or "New conversation"
        conversation.updated_at = datetime.now(UTC)
        db.commit()

        retrieved_chunks = retrieve_relevant_chunks(db, conversation.user_id, content)
        citations = [
            {
                "index": index,
                "chunkId": str(chunk.id),
                "documentId": str(document.id),
                "filename": document.filename,
                "excerpt": chunk.content[:180],
            }
            for index, (chunk, document, _) in enumerate(retrieved_chunks, start=1)
        ]
        yield format_sse("meta", json.dumps({"citations": citations}))

        prompt = build_prompt(content, history, retrieved_chunks)
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

        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="".join(output_parts).strip(),
            citations=citations,
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
                "createdAt": assistant_message.created_at.isoformat(),
            }
        }
        yield format_sse("done", json.dumps(payload))
