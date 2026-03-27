import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.models import Conversation, Document, DocumentChunk
from app.services.metadata import extract_json_object, get_completion_text
from app.services.tracing import traceable


sql_client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex|analyze|replace|"
    r"grant|revoke|truncate|begin|commit|rollback|savepoint|release"
    r")\b",
    re.IGNORECASE,
)
DOCUMENT_TERMS = ("document", "documents", "doc", "docs", "file", "files", "upload", "uploads")
CONVERSATION_TERMS = ("conversation", "conversations", "thread", "threads", "chat", "chats")
MESSAGE_TERMS = ("message", "messages")
TOPIC_TERMS = ("topic", "topics")
ENTITY_TERMS = ("entity", "entities")
LANGUAGE_TERMS = ("language", "languages")

WORKSPACE_SCHEMA_DESCRIPTION = """
documents(
  id TEXT,
  filename TEXT,
  source_key TEXT,
  version INTEGER,
  status TEXT,
  last_ingestion_result TEXT,
  metadata_status TEXT,
  document_type TEXT,
  language TEXT,
  summary TEXT,
  topic_count INTEGER,
  entity_count INTEGER,
  chunk_count INTEGER,
  created_at TEXT,
  updated_at TEXT,
  metadata_extracted_at TEXT
)
document_topics(
  document_id TEXT,
  filename TEXT,
  topic TEXT
)
document_entities(
  document_id TEXT,
  filename TEXT,
  entity TEXT
)
conversations(
  id TEXT,
  title TEXT,
  created_at TEXT,
  updated_at TEXT,
  message_count INTEGER,
  user_message_count INTEGER,
  assistant_message_count INTEGER,
  last_message_at TEXT
)
messages(
  id TEXT,
  conversation_id TEXT,
  conversation_title TEXT,
  role TEXT,
  content TEXT,
  citation_count INTEGER,
  created_at TEXT
)
""".strip()


class SQLGenerationPayload(BaseModel):
    can_answer: bool = True
    sql: str | None = None
    rationale: str = Field(default="")


@dataclass(slots=True)
class WorkspaceSQLResult:
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    rationale: str = ""
    truncated: bool = False

    def preview_text(self) -> str:
        if not self.rows:
            return "The SQL query returned no rows."

        preview_payload = {
            "columns": self.columns,
            "rows": self.rows,
            "rowCount": self.row_count,
            "truncated": self.truncated,
        }
        return json.dumps(preview_payload, default=str)


def serialize_sql_value(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, default=str)
    return str(value)


def normalize_question(question: str) -> str:
    return " ".join(question.lower().split())


def contains_any(content: str, terms: tuple[str, ...]) -> bool:
    return any(term in content for term in terms)


def heuristic_sql_for_question(question: str) -> str | None:
    normalized = normalize_question(question)

    if re.search(r"\b(how many|count|number of|total)\b", normalized):
        if contains_any(normalized, DOCUMENT_TERMS):
            if re.search(r"\b(by|per)\b.*\b(type|document type)\b", normalized):
                return (
                    "SELECT COALESCE(document_type, 'unknown') AS document_type, "
                    "COUNT(*) AS document_count "
                    "FROM documents "
                    "GROUP BY COALESCE(document_type, 'unknown') "
                    "ORDER BY document_count DESC, document_type ASC "
                    f"LIMIT {settings.sql_tool_row_limit}"
                )
            if re.search(r"\b(by|per)\b.*\b(language|languages)\b", normalized):
                return (
                    "SELECT COALESCE(language, 'unknown') AS language, "
                    "COUNT(*) AS document_count "
                    "FROM documents "
                    "GROUP BY COALESCE(language, 'unknown') "
                    "ORDER BY document_count DESC, language ASC "
                    f"LIMIT {settings.sql_tool_row_limit}"
                )
            if "completed" in normalized:
                return "SELECT COUNT(*) AS document_count FROM documents WHERE status = 'completed'"
            if "failed" in normalized:
                return "SELECT COUNT(*) AS document_count FROM documents WHERE status = 'failed'"
            if "processing" in normalized:
                return "SELECT COUNT(*) AS document_count FROM documents WHERE status = 'processing'"
            if "queued" in normalized:
                return "SELECT COUNT(*) AS document_count FROM documents WHERE status = 'queued'"
            return "SELECT COUNT(*) AS document_count FROM documents"

        if contains_any(normalized, CONVERSATION_TERMS):
            return "SELECT COUNT(*) AS conversation_count FROM conversations"

        if contains_any(normalized, MESSAGE_TERMS):
            if "assistant" in normalized:
                return "SELECT COUNT(*) AS assistant_message_count FROM messages WHERE role = 'assistant'"
            if "user" in normalized:
                return "SELECT COUNT(*) AS user_message_count FROM messages WHERE role = 'user'"
            return "SELECT COUNT(*) AS message_count FROM messages"

    if contains_any(normalized, LANGUAGE_TERMS) and re.search(r"\b(which|what|list|show)\b", normalized):
        return (
            "SELECT DISTINCT language "
            "FROM documents "
            "WHERE language IS NOT NULL AND TRIM(language) <> '' "
            "ORDER BY language ASC "
            f"LIMIT {settings.sql_tool_row_limit}"
        )

    if contains_any(normalized, TOPIC_TERMS) and re.search(r"\b(which|what|list|show|top)\b", normalized):
        return (
            "SELECT topic, COUNT(*) AS document_count "
            "FROM document_topics "
            "GROUP BY topic "
            "ORDER BY document_count DESC, topic ASC "
            f"LIMIT {settings.sql_tool_row_limit}"
        )

    if contains_any(normalized, ENTITY_TERMS) and re.search(r"\b(which|what|list|show|top)\b", normalized):
        return (
            "SELECT entity, COUNT(*) AS document_count "
            "FROM document_entities "
            "GROUP BY entity "
            "ORDER BY document_count DESC, entity ASC "
            f"LIMIT {settings.sql_tool_row_limit}"
        )

    if contains_any(normalized, DOCUMENT_TERMS) and re.search(r"\b(list|show|latest|newest|oldest)\b", normalized):
        order_by = "updated_at DESC"
        if "oldest" in normalized:
            order_by = "updated_at ASC"
        return (
            "SELECT filename, status, version, COALESCE(document_type, 'unknown') AS document_type, "
            "COALESCE(language, 'unknown') AS language, updated_at "
            "FROM documents "
            f"ORDER BY {order_by} "
            f"LIMIT {settings.sql_tool_row_limit}"
        )

    if contains_any(normalized, CONVERSATION_TERMS) and re.search(r"\b(list|show|latest|newest|oldest)\b", normalized):
        order_by = "updated_at DESC"
        if "oldest" in normalized:
            order_by = "updated_at ASC"
        return (
            "SELECT title, message_count, user_message_count, assistant_message_count, updated_at "
            "FROM conversations "
            f"ORDER BY {order_by} "
            f"LIMIT {settings.sql_tool_row_limit}"
        )

    if contains_any(normalized, DOCUMENT_TERMS) and "status" in normalized:
        return (
            "SELECT status, COUNT(*) AS document_count "
            "FROM documents "
            "GROUP BY status "
            "ORDER BY document_count DESC, status ASC "
            f"LIMIT {settings.sql_tool_row_limit}"
        )

    return None


def build_workspace_connection(db: Session, user_id: UUID) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    connection.executescript(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            source_key TEXT NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL,
            last_ingestion_result TEXT,
            metadata_status TEXT NOT NULL,
            document_type TEXT,
            language TEXT,
            summary TEXT,
            topic_count INTEGER NOT NULL,
            entity_count INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            metadata_extracted_at TEXT
        );

        CREATE TABLE document_topics (
            document_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            topic TEXT NOT NULL
        );

        CREATE TABLE document_entities (
            document_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            entity TEXT NOT NULL
        );

        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            message_count INTEGER NOT NULL,
            user_message_count INTEGER NOT NULL,
            assistant_message_count INTEGER NOT NULL,
            last_message_at TEXT
        );

        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            conversation_title TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            citation_count INTEGER NOT NULL,
            created_at TEXT
        );
        """
    )

    chunk_counts = dict(
        db.execute(
            select(DocumentChunk.document_id, func.count(DocumentChunk.id))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.user_id == user_id)
            .group_by(DocumentChunk.document_id)
        ).all()
    )

    document_statement = select(Document).where(Document.user_id == user_id).order_by(Document.updated_at.desc())
    documents = list(db.scalars(document_statement))
    for document in documents:
        metadata = document.extracted_metadata or {}
        topics = [item for item in metadata.get("topics", []) if isinstance(item, str) and item.strip()]
        entities = [item for item in metadata.get("entities", []) if isinstance(item, str) and item.strip()]

        connection.execute(
            """
            INSERT INTO documents (
                id, filename, source_key, version, status, last_ingestion_result, metadata_status,
                document_type, language, summary, topic_count, entity_count, chunk_count,
                created_at, updated_at, metadata_extracted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(document.id),
                document.filename,
                document.source_key,
                document.version,
                document.status,
                document.last_ingestion_result,
                document.metadata_status,
                metadata.get("document_type"),
                metadata.get("language"),
                metadata.get("summary"),
                len(topics),
                len(entities),
                int(chunk_counts.get(document.id, 0) or 0),
                document.created_at.isoformat() if document.created_at else None,
                document.updated_at.isoformat() if document.updated_at else None,
                document.metadata_extracted_at.isoformat() if document.metadata_extracted_at else None,
            ),
        )

        if topics:
            connection.executemany(
                "INSERT INTO document_topics (document_id, filename, topic) VALUES (?, ?, ?)",
                [(str(document.id), document.filename, topic) for topic in topics],
            )
        if entities:
            connection.executemany(
                "INSERT INTO document_entities (document_id, filename, entity) VALUES (?, ?, ?)",
                [(str(document.id), document.filename, entity) for entity in entities],
            )

    conversation_statement = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    conversations = list(db.scalars(conversation_statement))
    for conversation in conversations:
        ordered_messages = sorted(conversation.messages, key=lambda item: item.created_at)
        user_message_count = sum(1 for message in ordered_messages if message.role == "user")
        assistant_message_count = sum(1 for message in ordered_messages if message.role == "assistant")
        last_message_at = ordered_messages[-1].created_at.isoformat() if ordered_messages else None

        connection.execute(
            """
            INSERT INTO conversations (
                id, title, created_at, updated_at, message_count, user_message_count,
                assistant_message_count, last_message_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(conversation.id),
                conversation.title,
                conversation.created_at.isoformat() if conversation.created_at else None,
                conversation.updated_at.isoformat() if conversation.updated_at else None,
                len(ordered_messages),
                user_message_count,
                assistant_message_count,
                last_message_at,
            ),
        )

        if ordered_messages:
            connection.executemany(
                """
                INSERT INTO messages (
                    id, conversation_id, conversation_title, role, content, citation_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(message.id),
                        str(conversation.id),
                        conversation.title,
                        message.role,
                        message.content,
                        len(message.citations or []),
                        message.created_at.isoformat() if message.created_at else None,
                    )
                    for message in ordered_messages
                ],
            )

    connection.commit()
    return connection


def build_sql_generation_messages(question: str, *, previous_sql: str | None = None, error: str | None = None) -> list[dict[str, str]]:
    system_prompt = (
        "You translate questions about a local RAG workspace into a single SQLite SELECT query. "
        "Return a JSON object with keys can_answer, sql, and rationale. "
        "Only use the provided tables. "
        "Only generate a SELECT statement or a WITH ... SELECT statement. "
        "Never use semicolons. "
        "Never modify data. "
        f"Apply LIMIT {settings.sql_tool_row_limit} to non-aggregate listing queries. "
        "Use lower(column) LIKE '%term%' for case-insensitive substring matching when appropriate. "
        "If the question requires document chunk text or outside-world knowledge rather than this structured schema, set can_answer to false."
    )

    repair_context = ""
    if previous_sql and error:
        repair_context = (
            "\n\nThe previous SQL attempt failed.\n"
            f"Previous SQL:\n{previous_sql}\n\n"
            f"SQLite error:\n{error}\n\n"
            "Return a corrected query."
        )

    user_prompt = (
        "Available SQLite tables:\n"
        f"{WORKSPACE_SCHEMA_DESCRIPTION}\n\n"
        f"User question:\n{question}"
        f"{repair_context}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def request_sql_payload(messages: list[dict[str, str]]) -> SQLGenerationPayload:
    request_kwargs = {
        "model": settings.llm_chat_model,
        "messages": messages,
        "temperature": 0,
    }
    try:
        response = sql_client.chat.completions.create(
            **request_kwargs,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = sql_client.chat.completions.create(**request_kwargs)

    if not response.choices:
        raise ValueError("SQL generation returned no choices")

    raw_text = get_completion_text(response.choices[0].message.content)
    try:
        payload = json.loads(extract_json_object(raw_text))
    except json.JSONDecodeError as exc:
        raise ValueError("SQL generation returned invalid JSON") from exc

    try:
        return SQLGenerationPayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("SQL generation returned an unexpected schema") from exc


def sanitize_sql(sql: str) -> str:
    cleaned = " ".join(sql.strip().split())
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    return cleaned


def validate_sql(sql: str) -> None:
    cleaned = sanitize_sql(sql)
    lowered = cleaned.lower()
    if not cleaned:
        raise ValueError("SQL generation returned an empty query")
    if ";" in cleaned:
        raise ValueError("Only single SQL statements are allowed")
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise ValueError("Only SELECT queries are allowed")
    if FORBIDDEN_SQL_PATTERN.search(cleaned):
        raise ValueError("The SQL query included a forbidden statement")
    if "sqlite_" in lowered:
        raise ValueError("System SQLite tables are not available")


def execute_sql(connection: sqlite3.Connection, sql: str) -> WorkspaceSQLResult:
    validate_sql(sql)

    cursor = connection.execute(sql)
    columns = [description[0] for description in cursor.description or []]
    fetched_rows = cursor.fetchmany(settings.sql_tool_row_limit + 1)
    truncated = len(fetched_rows) > settings.sql_tool_row_limit
    visible_rows = fetched_rows[: settings.sql_tool_row_limit]
    serialized_rows = [
        {column: serialize_sql_value(row[column]) for column in columns}
        for row in visible_rows
    ]
    return WorkspaceSQLResult(
        sql=sanitize_sql(sql),
        columns=columns,
        rows=serialized_rows,
        row_count=len(serialized_rows),
        truncated=truncated,
    )


@traceable(name="workspace-sql", run_type="chain")
def run_workspace_sql(db: Session, user_id: UUID, question: str) -> WorkspaceSQLResult | None:
    connection = build_workspace_connection(db, user_id)
    try:
        try:
            heuristic_sql = heuristic_sql_for_question(question)
            if heuristic_sql:
                result = execute_sql(connection, heuristic_sql)
                result.rationale = "matched deterministic workspace analytics route"
                return result

            payload = request_sql_payload(build_sql_generation_messages(question))
            if not payload.can_answer or not payload.sql:
                return None

            try:
                result = execute_sql(connection, payload.sql)
                result.rationale = payload.rationale
                return result
            except Exception as first_error:
                repaired_payload = request_sql_payload(
                    build_sql_generation_messages(question, previous_sql=payload.sql, error=str(first_error))
                )
                if not repaired_payload.can_answer or not repaired_payload.sql:
                    return None

                repaired_result = execute_sql(connection, repaired_payload.sql)
                repaired_result.rationale = repaired_payload.rationale
                return repaired_result
        except Exception:
            return None
    finally:
        connection.close()
