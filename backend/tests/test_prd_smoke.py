from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import UTC, datetime
from httpx import Request, Response
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.models import Conversation, ConversationPIIRegistryEntry, Document, DocumentChunk, Folder, IngestionJob, Message
from app.db.session import SessionLocal, bind_current_user_context, engine
from app.services.auth import authenticate_user, register_user
from app.services.chat import stream_conversation_reply
from app.services.document_parser_ocr import DocumentExtractionError, ParserDependencyError, parse_document_file
from app.services.documents import prepare_document_upload, process_document, stream_document_status
from app.services.embeddings import EmbeddingProviderError, embed_texts
from app.services.knowledge_base import execute_glob, execute_grep, execute_read
from app.services.redaction import ConversationRedactionSession, DetectedPIIEntity, build_redaction_session
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
                    "TRUNCATE TABLE conversation_pii_registry_entries, document_chunks, ingestion_jobs, messages, "
                    "conversations, documents, folders, users RESTART IDENTITY CASCADE"
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
        folder_id: uuid.UUID | None = None,
        source_key: str | None = None,
        language: str | None = None,
        topics: list[str] | None = None,
        entities: list[str] | None = None,
        full_markdown: str | None = None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        with SessionLocal() as db:
            bind_current_user_context(db, str(user_id))
            now = datetime.now(UTC)
            document = Document(
                user_id=user_id,
                folder_id=folder_id,
                filename=filename,
                source_key=source_key or filename,
                storage_path=f"/tmp/{filename}",
                full_markdown=full_markdown or f"# {filename}\n\nChunk content for {filename}",
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

    def create_folder(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        scope: str = "private",
        parent_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        with SessionLocal() as db:
            bind_current_user_context(db, str(user_id))
            folder = Folder(user_id=user_id, name=name, scope=scope, parent_id=parent_id)
            db.add(folder)
            db.commit()
            return folder.id

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

    def create_conversation(self, *, user_id: uuid.UUID, title: str = "New conversation") -> uuid.UUID:
        with SessionLocal() as db:
            bind_current_user_context(db, str(user_id))
            conversation = Conversation(user_id=user_id, title=title)
            db.add(conversation)
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

    def test_global_folders_and_documents_are_visible_across_users(self) -> None:
        owner_id, _ = self.register_account()
        viewer_id, _ = self.register_account()
        private_folder_id = self.create_folder(user_id=owner_id, name="owner-private", scope="private")
        global_folder_id = self.create_folder(user_id=owner_id, name="team-shared", scope="global")
        self.create_completed_document(user_id=owner_id, filename="private-note.md", folder_id=private_folder_id)
        self.create_completed_document(user_id=owner_id, filename="shared-note.md", folder_id=global_folder_id)
        self.create_completed_document(user_id=viewer_id, filename="viewer-note.md")

        with SessionLocal() as db:
            bind_current_user_context(db, str(viewer_id))
            visible_folders = list(db.scalars(select(Folder).order_by(Folder.name)))
            visible_documents = list(db.scalars(select(Document).order_by(Document.filename)))

        self.assertEqual([item.name for item in visible_folders], ["team-shared"])
        self.assertEqual([item.filename for item in visible_documents], ["shared-note.md", "viewer-note.md"])

    def test_knowledge_base_tools_support_grep_glob_and_read(self) -> None:
        user_id, _ = self.register_account()
        reports_folder_id = self.create_folder(user_id=user_id, name="reports", scope="private")
        document_id, _ = self.create_completed_document(
            user_id=user_id,
            filename="q1-report.md",
            folder_id=reports_folder_id,
            full_markdown="# Q1 Report\n\nAlpha line\nBeta mention\nGamma close",
        )

        with SessionLocal() as db:
            bind_current_user_context(db, str(user_id))
            grep_result = execute_grep(db, user_id, "Beta", "/private/reports")
            glob_result = execute_glob(db, user_id, "reports/*.md")
            read_result = execute_read(db, user_id, document_id, start_line=4, end_line=4)

        self.assertEqual([item["filename"] for item in grep_result["matches"]], ["q1-report.md"])
        self.assertEqual([item["filename"] for item in glob_result["matches"]], ["q1-report.md"])
        self.assertEqual(read_result["content"], "Beta mention")

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

    def test_redaction_registry_persists_surrogates_and_keeps_hard_redactions_irreversible(self) -> None:
        user_id, _ = self.register_account()
        conversation_id = self.create_conversation(user_id=user_id, title="PII thread")
        original_text = "John Smith emailed john@example.com yesterday."
        hard_redaction_text = "Card 4111-1111-1111-1111 should be removed."

        person_start = original_text.index("John Smith")
        email_start = original_text.index("john@example.com")
        card_start = hard_redaction_text.index("4111-1111-1111-1111")
        original_entities = [
            DetectedPIIEntity(
                start=person_start,
                end=person_start + len("John Smith"),
                entity_type="PERSON",
                text="John Smith",
                score=0.99,
            ),
            DetectedPIIEntity(
                start=email_start,
                end=email_start + len("john@example.com"),
                entity_type="EMAIL_ADDRESS",
                text="john@example.com",
                score=0.99,
            ),
        ]
        hard_entities = [
            DetectedPIIEntity(
                start=card_start,
                end=card_start + len("4111-1111-1111-1111"),
                entity_type="CREDIT_CARD",
                text="4111-1111-1111-1111",
                score=0.99,
            )
        ]

        previous = settings.pii_redaction_enabled
        settings.pii_redaction_enabled = True
        try:
            with SessionLocal() as db:
                bind_current_user_context(db, str(user_id))
                session = build_redaction_session(db, conversation_id=conversation_id, user_id=user_id)
                with patch.object(ConversationRedactionSession, "detect_entities", return_value=original_entities):
                    anonymized = session.anonymize_text(original_text)
                with patch.object(ConversationRedactionSession, "detect_entities", return_value=hard_entities):
                    hard_anonymized = session.anonymize_text(hard_redaction_text)
                db.commit()

            self.assertNotIn("John Smith", anonymized)
            self.assertNotIn("john@example.com", anonymized)
            with SessionLocal() as db:
                bind_current_user_context(db, str(user_id))
                persisted_session = build_redaction_session(db, conversation_id=conversation_id, user_id=user_id)
                self.assertEqual(persisted_session.deanonymize_text(anonymized), original_text)
                self.assertEqual(
                    persisted_session.deanonymize_text(hard_anonymized),
                    "Card [CREDIT_CARD] should be removed.",
                )

            with SessionLocal() as db:
                bind_current_user_context(db, str(user_id))
                repeated_session = build_redaction_session(db, conversation_id=conversation_id, user_id=user_id)
                with patch.object(ConversationRedactionSession, "detect_entities", return_value=original_entities):
                    repeated_anonymized = repeated_session.anonymize_text(original_text)

            self.assertEqual(anonymized, repeated_anonymized)
        finally:
            settings.pii_redaction_enabled = previous

    def test_stream_chat_buffers_and_deanonymizes_redacted_output_before_tokens(self) -> None:
        user_id, _ = self.register_account()
        conversation_id = self.create_conversation(user_id=user_id, title="Privacy stream")

        previous_redaction = settings.pii_redaction_enabled
        previous_web = settings.web_search_enabled
        settings.pii_redaction_enabled = True
        settings.web_search_enabled = False

        try:
            with SessionLocal() as db:
                bind_current_user_context(db, str(user_id))
                db.add(
                    ConversationPIIRegistryEntry(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        entity_type="PERSON",
                        normalized_value="john smith",
                        real_value="John Smith",
                        surrogate_value="Marcus Smith",
                        cluster_key="person-1",
                        profile={
                            "raw": "John Smith",
                            "first": "John",
                            "last": "Smith",
                            "canonical_first": "john",
                            "form": "full",
                            "family": {
                                "cluster_key": "person-1",
                                "real_first": "John",
                                "real_last": "Smith",
                                "canonical_first": "john",
                                "surrogate_first": "Marcus",
                                "surrogate_last": "Smith",
                                "gender": "male",
                            },
                        },
                    )
                )
                db.commit()

            question = "Summarize John Smith's status."
            question_start = question.index("John Smith")
            entities = [
                DetectedPIIEntity(
                    start=question_start,
                    end=question_start + len("John Smith"),
                    entity_type="PERSON",
                    text="John Smith",
                    score=0.99,
                )
            ]

            captured_messages: list[dict[str, str]] = []

            def fake_stream_create(*, model, messages, temperature, stream):  # noqa: ANN001
                self.assertTrue(stream)
                captured_messages.extend(messages)
                return [
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="Marcus Smith reviewed the file."))]
                    )
                ]

            with patch.object(ConversationRedactionSession, "detect_entities", return_value=entities), patch(
                "app.services.chat.retrieve_relevant_chunks",
                return_value=[],
            ), patch("app.services.chat.should_run_web_search", return_value=False), patch(
                "app.services.chat.client.chat.completions.create",
                side_effect=fake_stream_create,
            ):
                events = list(stream_conversation_reply(str(conversation_id), str(user_id), question))

            serialized_prompt = json.dumps(captured_messages)
            self.assertNotIn("John Smith", serialized_prompt)
            self.assertIn("Marcus Smith", serialized_prompt)

            token_text = "".join(
                json.loads(line.removeprefix("data: "))["text"]
                for event in events
                if event.startswith("event: token")
                for line in event.splitlines()
                if line.startswith("data: ")
            )
            self.assertEqual(token_text, "John Smith reviewed the file.")
            self.assertNotIn("Marcus Smith", token_text)

            redaction_events = [
                json.loads(line.removeprefix("data: "))
                for event in events
                if event.startswith("event: redaction_status")
                for line in event.splitlines()
                if line.startswith("data: ")
            ]
            self.assertEqual([item["stage"] for item in redaction_events], ["anonymizing", "deanonymizing"])
        finally:
            settings.pii_redaction_enabled = previous_redaction
            settings.web_search_enabled = previous_web

    def test_web_search_query_is_anonymized_before_external_fallback(self) -> None:
        user_id, _ = self.register_account()
        conversation_id = self.create_conversation(user_id=user_id, title="Privacy web fallback")

        previous_redaction = settings.pii_redaction_enabled
        previous_web = settings.web_search_enabled
        settings.pii_redaction_enabled = True
        settings.web_search_enabled = True

        question = (
            "Rewrite this exactly: John Smith emailed john@example.com. "
            "His credit card is 4111-1111-1111-1111."
        )
        person_start = question.index("John Smith")
        email_start = question.index("john@example.com")
        card_start = question.index("4111-1111-1111-1111")
        entities = [
            DetectedPIIEntity(
                start=person_start,
                end=person_start + len("John Smith"),
                entity_type="PERSON",
                text="John Smith",
                score=0.99,
            ),
            DetectedPIIEntity(
                start=email_start,
                end=email_start + len("john@example.com"),
                entity_type="EMAIL_ADDRESS",
                text="john@example.com",
                score=0.99,
            ),
            DetectedPIIEntity(
                start=card_start,
                end=card_start + len("4111-1111-1111-1111"),
                entity_type="CREDIT_CARD",
                text="4111-1111-1111-1111",
                score=0.99,
            ),
        ]

        captured_queries: list[str] = []

        def fake_search_web(query: str) -> SimpleNamespace:
            captured_queries.append(query)
            return SimpleNamespace(results=[], error=None, provider="stub")

        def fake_stream_create(*, model, messages, temperature, stream):  # noqa: ANN001
            self.assertTrue(stream)
            return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Done."))])]

        try:
            with patch.object(ConversationRedactionSession, "detect_entities", return_value=entities), patch(
                "app.services.chat.retrieve_relevant_chunks",
                return_value=[],
            ), patch("app.services.chat.should_run_web_search", return_value=True), patch(
                "app.services.chat.search_web",
                side_effect=fake_search_web,
            ), patch(
                "app.services.chat.client.chat.completions.create",
                side_effect=fake_stream_create,
            ):
                list(stream_conversation_reply(str(conversation_id), str(user_id), question))

            self.assertEqual(len(captured_queries), 1)
            self.assertNotIn("John Smith", captured_queries[0])
            self.assertNotIn("john@example.com", captured_queries[0])
            self.assertNotIn("4111-1111-1111-1111", captured_queries[0])
            self.assertIn("[CREDIT_CARD]", captured_queries[0])
        finally:
            settings.pii_redaction_enabled = previous_redaction
            settings.web_search_enabled = previous_web

    def test_literal_rewrite_request_skips_web_fallback_and_returns_no_web_citations(self) -> None:
        user_id, _ = self.register_account()
        conversation_id = self.create_conversation(user_id=user_id, title="Privacy rewrite")

        previous_redaction = settings.pii_redaction_enabled
        previous_web = settings.web_search_enabled
        settings.pii_redaction_enabled = True
        settings.web_search_enabled = True

        question = (
            "Rewrite this exactly, but keep all details: "
            "John Smith emailed john@example.com yesterday from Toronto. "
            "Call him at 416-555-0199. "
            "His credit card is 4111-1111-1111-1111."
        )
        person_start = question.index("John Smith")
        email_start = question.index("john@example.com")
        phone_start = question.index("416-555-0199")
        card_start = question.index("4111-1111-1111-1111")
        entities = [
            DetectedPIIEntity(
                start=person_start,
                end=person_start + len("John Smith"),
                entity_type="PERSON",
                text="John Smith",
                score=0.99,
            ),
            DetectedPIIEntity(
                start=email_start,
                end=email_start + len("john@example.com"),
                entity_type="EMAIL_ADDRESS",
                text="john@example.com",
                score=0.99,
            ),
            DetectedPIIEntity(
                start=phone_start,
                end=phone_start + len("416-555-0199"),
                entity_type="PHONE_NUMBER",
                text="416-555-0199",
                score=0.99,
            ),
            DetectedPIIEntity(
                start=card_start,
                end=card_start + len("4111-1111-1111-1111"),
                entity_type="CREDIT_CARD",
                text="4111-1111-1111-1111",
                score=0.99,
            ),
        ]

        captured_messages: list[dict[str, str]] = []

        def fake_stream_create(*, model, messages, temperature, stream):  # noqa: ANN001
            self.assertTrue(stream)
            captured_messages.extend(messages)
            user_prompt = messages[-1]["content"]
            anonymized_question = user_prompt.split("User question:\n", 1)[-1].strip()
            rewritten_text = anonymized_question.split(":", 1)[-1].strip()
            return [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=rewritten_text)
                        )
                    ]
                )
            ]

        try:
            with patch.object(ConversationRedactionSession, "detect_entities", return_value=entities), patch(
                "app.services.chat.retrieve_relevant_chunks",
                return_value=[],
            ), patch(
                "app.services.chat.search_web",
                side_effect=AssertionError("web fallback should not run for literal rewrite requests"),
            ), patch(
                "app.services.chat.client.chat.completions.create",
                side_effect=fake_stream_create,
            ):
                events = list(stream_conversation_reply(str(conversation_id), str(user_id), question))

            serialized_prompt = json.dumps(captured_messages)
            self.assertIn("Return only the transformed text.", serialized_prompt)
            self.assertIn("No web search requested.", serialized_prompt)

            done_payload = next(
                json.loads(line.removeprefix("data: "))
                for event in events
                if event.startswith("event: done")
                for line in event.splitlines()
                if line.startswith("data: ")
            )
            self.assertEqual(done_payload["message"]["citations"], [])
            self.assertEqual(
                done_payload["message"]["content"],
                "John Smith emailed john@example.com yesterday from Toronto. "
                "Call him at 416-555-0199. "
                "His credit card is [CREDIT_CARD].",
            )
        finally:
            settings.pii_redaction_enabled = previous_redaction
            settings.web_search_enabled = previous_web


if __name__ == "__main__":
    unittest.main()
