from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import UTC, datetime
from httpx import Request, Response
from pathlib import Path
import sys
from unittest.mock import patch

from sqlalchemy import select, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.models import Conversation, Document, DocumentChunk, IngestionJob, Message
from app.db.session import SessionLocal, bind_current_user_context, engine
from app.services.auth import authenticate_user, register_user
from app.services.document_parser_ocr import DocumentExtractionError, ParserDependencyError, parse_document_file
from app.services.documents import prepare_document_upload, process_document, stream_document_status
from app.services.embeddings import EmbeddingProviderError, embed_texts
from app.services.sub_agents import select_sub_agent_targets
from app.services.web_search import search_web
from app.services.workspace_sql import run_workspace_sql


class PRDSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def tearDown(self) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE document_chunks, ingestion_jobs, messages, conversations, documents, users RESTART IDENTITY CASCADE"
                )
            )

    def register_account(self, email: str | None = None, password: str = "Test123456!") -> tuple[uuid.UUID, str]:
        address = email or f"{uuid.uuid4()}@example.com"
        with SessionLocal() as db:
            user = register_user(db, address, password)
            token = authenticate_user(db, address, password)
            return user.id, token

    def create_completed_document(
        self,
        *,
        user_id: uuid.UUID,
        filename: str,
        source_key: str | None = None,
        language: str | None = None,
        topics: list[str] | None = None,
        entities: list[str] | None = None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        with SessionLocal() as db:
            bind_current_user_context(db, str(user_id))
            now = datetime.now(UTC)
            document = Document(
                user_id=user_id,
                filename=filename,
                source_key=source_key or filename,
                storage_path=f"/tmp/{filename}",
                content_hash=str(uuid.uuid4().hex),
                hash_algorithm="sha256",
                version=1,
                last_ingestion_result="new",
                pending_filename=None,
                pending_storage_path=None,
                pending_content_hash=None,
                extracted_metadata={
                    "title": filename,
                    "summary": f"Summary for {filename}",
                    "document_type": "note",
                    "topics": topics or ["rag"],
                    "entities": entities or ["agent"],
                    "language": language,
                },
                metadata_schema_version=1,
                metadata_status="completed",
                metadata_error=None,
                metadata_extracted_at=now,
                status="completed",
                error_message=None,
            )
            db.add(document)
            db.flush()

            job = IngestionJob(
                document_id=document.id,
                status="completed",
                error_message=None,
                started_at=now,
                completed_at=now,
            )
            db.add(job)
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=0,
                    content=f"Chunk content for {filename}",
                    embedding=[0.0] * settings.llm_embed_dimensions,
                )
            )
            db.commit()
            return document.id, job.id

    def create_conversation_with_message(self, *, user_id: uuid.UUID, title: str) -> uuid.UUID:
        with SessionLocal() as db:
            bind_current_user_context(db, str(user_id))
            conversation = Conversation(user_id=user_id, title=title)
            db.add(conversation)
            db.flush()
            db.add(
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=f"Response for {title}",
                    citations=[],
                    agent_trace={},
                )
            )
            db.commit()
            return conversation.id

    def test_auth_bypass_allows_register_and_login_under_rls(self) -> None:
        user_id, token = self.register_account()
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], str(user_id))

    def test_row_level_security_scopes_documents_conversations_and_chunks(self) -> None:
        user_one, _ = self.register_account()
        user_two, _ = self.register_account()
        self.create_completed_document(user_id=user_one, filename="alpha.md", language="en")
        self.create_completed_document(user_id=user_two, filename="beta.md", language="fr")
        self.create_conversation_with_message(user_id=user_one, title="Alpha thread")
        self.create_conversation_with_message(user_id=user_two, title="Beta thread")

        with SessionLocal() as db:
            self.assertEqual(list(db.scalars(select(Document).order_by(Document.filename))), [])

        with SessionLocal() as db:
            bind_current_user_context(db, str(user_one))
            documents = list(db.scalars(select(Document).order_by(Document.filename)))
            chunks = list(db.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)))
            conversations = list(db.scalars(select(Conversation).order_by(Conversation.title)))
            self.assertEqual([item.filename for item in documents], ["alpha.md"])
            self.assertEqual(len(chunks), 1)
            self.assertEqual([item.title for item in conversations], ["Alpha thread"])

    def test_record_manager_marks_unchanged_reuploads_without_requeueing(self) -> None:
        user_id, _ = self.register_account()

        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = Path(temp_dir) / "notes.md"
            duplicate_path = Path(temp_dir) / "notes-copy.md"
            original_path.write_text("# Notes\n\nAgentic retrieval", encoding="utf-8")
            duplicate_path.write_text("# Notes\n\nAgentic retrieval", encoding="utf-8")

            with SessionLocal() as db:
                bind_current_user_context(db, str(user_id))
                document, should_queue = prepare_document_upload(
                    db,
                    user_id=str(user_id),
                    filename="notes.md",
                    source_key="notes.md",
                    storage_path=str(original_path),
                )
                self.assertTrue(should_queue)

                document.filename = "notes.md"
                document.storage_path = str(original_path)
                document.content_hash = document.pending_content_hash
                document.pending_filename = None
                document.pending_storage_path = None
                document.pending_content_hash = None
                document.version = 1
                document.status = "completed"
                document.last_ingestion_result = "new"
                document.metadata_status = "completed"
                document.ingestion_job.status = "completed"
                db.commit()

                duplicate_document, duplicate_should_queue = prepare_document_upload(
                    db,
                    user_id=str(user_id),
                    filename="notes.md",
                    source_key="notes.md",
                    storage_path=str(duplicate_path),
                )

                self.assertEqual(document.id, duplicate_document.id)
                self.assertFalse(duplicate_should_queue)
                self.assertEqual(duplicate_document.last_ingestion_result, "unchanged")

    def test_native_markdown_and_html_parsing_work_without_docling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = Path(temp_dir) / "notes.md"
            html_path = Path(temp_dir) / "page.html"
            markdown_path.write_text("# Notes\n\nAgentic retrieval is grounded.", encoding="utf-8")
            html_path.write_text("<html><body><h1>Guide</h1><p>Hybrid search helps.</p></body></html>", encoding="utf-8")

            markdown_result = parse_document_file(markdown_path, markdown_path.name)
            html_result = parse_document_file(html_path, html_path.name)

        self.assertIn("Agentic retrieval is grounded.", markdown_result.text_for_chunking)
        self.assertIn("Guide", html_result.text_for_chunking)
        self.assertIn("Hybrid search helps.", html_result.text_for_chunking)

    def test_docx_and_pdf_paths_fail_clearly_when_docling_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "draft.docx"
            pdf_path = Path(temp_dir) / "scan.pdf"
            docx_path.write_bytes(b"not-a-real-docx")
            pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

            with self.assertRaises(ParserDependencyError):
                parse_document_file(docx_path, docx_path.name)

            with self.assertRaises((ParserDependencyError, DocumentExtractionError)):
                parse_document_file(pdf_path, pdf_path.name)

    def test_document_status_stream_emits_document_then_done(self) -> None:
        user_id, _ = self.register_account()
        document_id, _ = self.create_completed_document(user_id=user_id, filename="streamed.md", language="en")

        events = list(stream_document_status(str(document_id), str(user_id), poll_interval_seconds=0))
        self.assertGreaterEqual(len(events), 2)
        self.assertTrue(events[0].startswith("event: document"))
        self.assertTrue(events[1].startswith("event: done"))

        payload_line = [line for line in events[0].splitlines() if line.startswith("data: ")][0]
        payload = json.loads(payload_line.removeprefix("data: "))
        self.assertEqual(payload["document"]["filename"], "streamed.md")

    def test_embedding_connection_failures_are_reported_clearly(self) -> None:
        from openai import APIConnectionError

        request = Request("POST", "http://127.0.0.1:11434/v1/embeddings")
        with patch(
            "app.services.embeddings.embed_client.embeddings.create",
            side_effect=APIConnectionError(request=request),
        ):
            with self.assertRaises(EmbeddingProviderError) as context:
                embed_texts(["hello world"])

        self.assertIn("Embedding provider unavailable", str(context.exception))
        self.assertIn(settings.llm_embed_url.rstrip("/"), str(context.exception))

    def test_embedding_model_not_found_failures_are_reported_clearly(self) -> None:
        from openai import NotFoundError

        request = Request("POST", "http://127.0.0.1:11434/v1/embeddings")
        response = Response(404, request=request)
        with patch(
            "app.services.embeddings.embed_client.embeddings.create",
            side_effect=NotFoundError("not found", response=response, body={"error": "missing"}),
        ):
            with self.assertRaises(EmbeddingProviderError) as context:
                embed_texts(["hello world"])

        self.assertIn("was not found", str(context.exception))

    def test_ingestion_failure_before_metadata_keeps_metadata_not_started(self) -> None:
        user_id, _ = self.register_account()

        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = Path(temp_dir) / "notes.md"
            markdown_path.write_text("# Notes\n\nAgentic retrieval is grounded.", encoding="utf-8")

            with SessionLocal() as db:
                bind_current_user_context(db, str(user_id))
                document, should_queue = prepare_document_upload(
                    db,
                    user_id=str(user_id),
                    filename=markdown_path.name,
                    source_key=markdown_path.name,
                    storage_path=str(markdown_path),
                )
                self.assertTrue(should_queue)
                ingestion_job = document.ingestion_job
                self.assertIsNotNone(ingestion_job)
                document_id = str(document.id)
                ingestion_job_id = str(ingestion_job.id)

            with patch(
                "app.services.documents.embed_texts",
                side_effect=EmbeddingProviderError("Embedding provider unavailable at http://127.0.0.1:11434/v1 for model nomic-embed-text."),
            ):
                process_document(document_id, ingestion_job_id, str(user_id))

            with SessionLocal() as db:
                bind_current_user_context(db, str(user_id))
                failed_document = db.get(Document, document_id)
                failed_job = db.get(IngestionJob, ingestion_job_id)

            self.assertIsNotNone(failed_document)
            self.assertIsNotNone(failed_job)
            self.assertEqual(failed_document.status, "failed")
            self.assertEqual(failed_document.metadata_status, "not_started")
            self.assertIsNone(failed_document.metadata_error)
            self.assertIn("Embedding provider unavailable", failed_job.error_message)

    def test_workspace_sql_heuristics_remain_user_scoped(self) -> None:
        user_one, _ = self.register_account()
        user_two, _ = self.register_account()
        self.create_completed_document(user_id=user_one, filename="english.md", language="en")
        self.create_completed_document(user_id=user_one, filename="french.md", language="fr")
        self.create_completed_document(user_id=user_two, filename="spanish.md", language="es")

        with SessionLocal() as db:
            bind_current_user_context(db, str(user_one))
            result = run_workspace_sql(db, user_one, "How many documents do I have by language?")

        self.assertIsNotNone(result)
        self.assertEqual(result.columns, ["language", "document_count"])
        self.assertEqual(result.rows, [{"language": "en", "document_count": 1}, {"language": "fr", "document_count": 1}])

    def test_sub_agent_target_selection_prefers_explicit_document_matches(self) -> None:
        user_id, _ = self.register_account()
        self.create_completed_document(user_id=user_id, filename="alpha-plan.md", language="en")
        self.create_completed_document(user_id=user_id, filename="beta-plan.md", language="en")

        with SessionLocal() as db:
            bind_current_user_context(db, str(user_id))
            targets = select_sub_agent_targets(db, user_id, "Summarize alpha-plan.md from start to finish", [])

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].document.filename, "alpha-plan.md")
        self.assertIn("explicit filename match", targets[0].selection_reason)

    def test_web_search_disabled_short_circuits_cleanly(self) -> None:
        previous = settings.web_search_enabled
        settings.web_search_enabled = False
        try:
            response = search_web("latest provider release")
        finally:
            settings.web_search_enabled = previous

        self.assertEqual(response.error, "Web search is disabled")


if __name__ == "__main__":
    unittest.main()
