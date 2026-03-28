import hashlib
import json
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.models import Document, DocumentChunk, IngestionJob
from app.db.session import SessionLocal, bind_current_user_context
from app.schemas.document import DocumentMoveRequest, DocumentResponse
from app.services.document_parser_ocr import (
    DocumentExtractionError,
    DocumentParserError,
    ParserDependencyError,
    UnsupportedDocumentFormatError,
    ensure_supported_document_filename,
    parse_document_file,
)
from app.services.embeddings import embed_texts
from app.services.folders import apply_document_visibility, get_document_target_folder
from app.services.metadata import METADATA_SCHEMA_VERSION, extract_document_metadata
from app.services.tracing import traceable
from app.utils.text import chunk_text, normalize_text


HASH_ALGORITHM = "sha256"
RUNNING_INGESTION_STATUSES = {"queued", "processing"}
TERMINAL_INGESTION_STATUSES = {"completed", "failed"}


def save_upload_file(upload: UploadFile) -> Path:
    try:
        ensure_supported_document_filename(upload.filename or "upload")
    except UnsupportedDocumentFormatError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "upload").suffix
    safe_name = f"{uuid.uuid4()}{suffix}"
    destination = settings.uploads_dir / safe_name
    try:
        with destination.open("wb") as target:
            while chunk := upload.file.read(1024 * 1024):
                target.write(chunk)
    finally:
        upload.file.close()
    return destination


def remove_uploaded_file(storage_path: str | None) -> None:
    if not storage_path:
        return

    path = Path(storage_path)
    for attempt in range(4):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 3:
                return
            time.sleep(0.25 * (attempt + 1))


def normalize_source_key(source_key: str | None, filename: str) -> str:
    cleaned = (source_key or "").strip()
    return cleaned or filename


def compute_content_hash(content: str) -> str:
    normalized = normalize_text(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_storage_hash(storage_path: str, filename: str | None = None) -> str:
    parsed_document = parse_document_file(storage_path, filename)
    return compute_content_hash(parsed_document.text_for_hashing)


def translate_upload_parser_error(exc: DocumentParserError) -> HTTPException:
    if isinstance(exc, (UnsupportedDocumentFormatError, DocumentExtractionError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, ParserDependencyError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


def has_active_document_content(document: Document) -> bool:
    return bool(document.content_hash and document.version > 0 and document.status == "completed")


def ensure_document_content_identity(document: Document) -> None:
    if document.content_hash or document.status != "completed":
        return

    try:
        document.content_hash = compute_storage_hash(document.storage_path, document.filename)
    except (DocumentParserError, FileNotFoundError):
        return

    document.hash_algorithm = HASH_ALGORITHM
    document.version = max(document.version, 1)
    if document.last_ingestion_result is None:
        document.last_ingestion_result = "new"


def reset_ingestion_job(ingestion_job: IngestionJob) -> None:
    ingestion_job.status = "queued"
    ingestion_job.error_message = None
    ingestion_job.started_at = None
    ingestion_job.completed_at = None


def snapshot_document_metadata(document: Document) -> dict[str, object | None]:
    return {
        "extracted_metadata": deepcopy(document.extracted_metadata),
        "metadata_schema_version": document.metadata_schema_version,
        "metadata_status": document.metadata_status,
        "metadata_error": document.metadata_error,
        "metadata_extracted_at": document.metadata_extracted_at,
    }


def restore_document_metadata(document: Document, snapshot: dict[str, object | None]) -> None:
    document.extracted_metadata = deepcopy(snapshot["extracted_metadata"])
    document.metadata_schema_version = snapshot["metadata_schema_version"]
    document.metadata_status = snapshot["metadata_status"] or "not_started"
    document.metadata_error = snapshot["metadata_error"]
    document.metadata_extracted_at = snapshot["metadata_extracted_at"]


def set_document_metadata_state(
    document: Document,
    *,
    extracted_metadata: dict | None,
    status: str,
    error: str | None,
    extracted_at: datetime | None,
) -> None:
    document.extracted_metadata = extracted_metadata
    document.metadata_schema_version = METADATA_SCHEMA_VERSION
    document.metadata_status = status
    document.metadata_error = error
    document.metadata_extracted_at = extracted_at


def prepare_document_upload(
    db: Session,
    *,
    user_id: str,
    filename: str,
    source_key: str | None,
    storage_path: str,
    folder_id: str | None = None,
) -> tuple[Document, bool]:
    target_folder = get_document_target_folder(db, folder_id=folder_id, user_id=user_id)
    resolved_source_key = normalize_source_key(source_key, filename)
    try:
        upload_hash = compute_storage_hash(storage_path, filename)
    except DocumentParserError as exc:
        raise translate_upload_parser_error(exc) from exc
    statement = (
        select(Document)
        .options(selectinload(Document.ingestion_job))
        .where(Document.user_id == user_id, Document.source_key == resolved_source_key)
    )
    document = db.scalar(statement)

    if document is None:
        document = Document(
            user_id=user_id,
            folder_id=target_folder.id if target_folder else None,
            filename=filename,
            source_key=resolved_source_key,
            storage_path=storage_path,
            full_markdown=None,
            content_hash=None,
            hash_algorithm=HASH_ALGORITHM,
            version=0,
            last_ingestion_result=None,
            pending_filename=None,
            pending_storage_path=None,
            pending_content_hash=upload_hash,
            extracted_metadata=None,
            metadata_schema_version=None,
            metadata_status="not_started",
            metadata_error=None,
            metadata_extracted_at=None,
            status="queued",
            error_message=None,
        )
        ingestion_job = IngestionJob(document=document, status="queued")
        db.add(document)
        db.add(ingestion_job)
        db.commit()
        return document, True

    ensure_document_content_identity(document)

    ingestion_job = document.ingestion_job
    if ingestion_job is None:
        ingestion_job = IngestionJob(document=document, status="completed" if has_active_document_content(document) else "queued")
        db.add(ingestion_job)

    if ingestion_job.status in RUNNING_INGESTION_STATUSES:
        if document.pending_content_hash and document.pending_content_hash == upload_hash:
            remove_uploaded_file(storage_path)
            return document, False
        remove_uploaded_file(storage_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is already being processed",
        )

    if has_active_document_content(document) and document.content_hash == upload_hash:
        now = datetime.now(UTC)
        remove_uploaded_file(storage_path)
        document.last_ingestion_result = "unchanged"
        document.error_message = None
        ingestion_job.status = "completed"
        ingestion_job.error_message = None
        ingestion_job.started_at = now
        ingestion_job.completed_at = now
        db.commit()
        return document, False

    document.source_key = resolved_source_key
    document.folder_id = target_folder.id if target_folder else None
    document.hash_algorithm = HASH_ALGORITHM
    document.error_message = None

    if has_active_document_content(document):
        document.pending_filename = filename
        document.pending_storage_path = storage_path
        document.pending_content_hash = upload_hash
    else:
        document.filename = filename
        document.storage_path = storage_path
        document.full_markdown = None
        document.content_hash = None
        document.pending_filename = None
        document.pending_storage_path = None
        document.pending_content_hash = upload_hash
        document.extracted_metadata = None
        document.metadata_schema_version = None
        document.metadata_status = "not_started"
        document.metadata_error = None
        document.metadata_extracted_at = None
        document.status = "queued"
        document.error_message = None
        document.last_ingestion_result = None

    reset_ingestion_job(ingestion_job)
    db.commit()
    return document, True


@traceable(name="process-document", run_type="chain")
def process_document(document_id: str, ingestion_job_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        bind_current_user_context(db, user_id)
        document = db.get(Document, document_id)
        ingestion_job = db.get(IngestionJob, ingestion_job_id)
        if not document or not ingestion_job:
            return

        has_active_content = has_active_document_content(document)
        candidate_storage_path = document.pending_storage_path or document.storage_path
        candidate_filename = document.pending_filename or document.filename
        candidate_hash = document.pending_content_hash or document.content_hash
        now = datetime.now(UTC)
        previous_metadata_state = snapshot_document_metadata(document)
        metadata_started = False

        if has_active_content:
            document.error_message = None
            document.metadata_status = "processing"
            document.metadata_error = None
        else:
            document.status = "processing"
            document.error_message = None
            document.metadata_status = "not_started"
            document.metadata_error = None
        ingestion_job.status = "processing"
        ingestion_job.error_message = None
        ingestion_job.started_at = now
        ingestion_job.completed_at = None
        db.commit()

        try:
            parsed_document = parse_document_file(candidate_storage_path, candidate_filename)
            content = parsed_document.text_for_chunking
            chunks = chunk_text(content, settings.chunk_size, settings.chunk_overlap)
            if not chunks:
                raise ValueError("The uploaded document does not contain any text to chunk")
            embeddings = embed_texts(chunks)
            if len(embeddings) != len(chunks):
                raise ValueError("Embedding provider returned an unexpected number of embeddings")
            metadata_started = True
            document.metadata_status = "processing"
            document.metadata_error = None
            metadata_payload: dict | None
            metadata_error: str | None
            try:
                metadata_payload = extract_document_metadata(candidate_filename, content)
                metadata_error = None
            except Exception as metadata_exc:
                metadata_payload = None
                metadata_error = str(metadata_exc)

            old_storage_path_to_delete = document.storage_path if document.pending_storage_path else None
            is_update = old_storage_path_to_delete is not None
            result_kind = "updated" if is_update else "new"
            next_version = max(document.version, 1) + 1 if is_update else max(document.version, 1)

            db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=False)):
                db.add(
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=chunk,
                        embedding=embedding,
                    )
                )

            document.filename = candidate_filename
            document.storage_path = candidate_storage_path
            document.full_markdown = parsed_document.text_for_chunking
            document.content_hash = candidate_hash or compute_content_hash(parsed_document.text_for_hashing)
            document.hash_algorithm = HASH_ALGORITHM
            document.version = next_version
            document.last_ingestion_result = result_kind
            document.pending_filename = None
            document.pending_storage_path = None
            document.pending_content_hash = None
            document.status = "completed"
            document.error_message = None
            completed_at = datetime.now(UTC)
            if metadata_payload is not None:
                set_document_metadata_state(
                    document,
                    extracted_metadata=metadata_payload,
                    status="completed",
                    error=None,
                    extracted_at=completed_at,
                )
            else:
                set_document_metadata_state(
                    document,
                    extracted_metadata=None,
                    status="failed",
                    error=metadata_error or "Metadata extraction did not return a valid payload",
                    extracted_at=None,
                )

            ingestion_job.status = "completed"
            ingestion_job.error_message = None
            ingestion_job.completed_at = completed_at
            db.commit()

            if old_storage_path_to_delete and old_storage_path_to_delete != candidate_storage_path:
                remove_uploaded_file(old_storage_path_to_delete)
        except Exception as exc:  # pragma: no cover - background task error path
            db.rollback()
            document = db.get(Document, document_id)
            ingestion_job = db.get(IngestionJob, ingestion_job_id)
            if not document or not ingestion_job:
                return

            pending_storage_path = document.pending_storage_path
            document.pending_filename = None
            document.pending_storage_path = None
            document.pending_content_hash = None

            if has_active_content:
                document.status = "completed"
                document.error_message = None
                restore_document_metadata(document, previous_metadata_state)
            else:
                document.status = "failed"
                document.error_message = str(exc)
                if metadata_started:
                    set_document_metadata_state(
                        document,
                        extracted_metadata=None,
                        status="failed",
                        error=str(exc),
                        extracted_at=None,
                    )
                else:
                    set_document_metadata_state(
                        document,
                        extracted_metadata=None,
                        status="not_started",
                        error=None,
                        extracted_at=None,
                    )

            ingestion_job.status = "failed"
            ingestion_job.error_message = str(exc)
            ingestion_job.completed_at = datetime.now(UTC)
            db.commit()

            if pending_storage_path:
                remove_uploaded_file(pending_storage_path)


def list_documents_for_user(db: Session, user_id: str) -> list[Document]:
    statement = (
        select(Document)
        .options(selectinload(Document.ingestion_job), selectinload(Document.folder))
        .order_by(Document.updated_at.desc())
    )
    return list(db.scalars(apply_document_visibility(statement, user_id)))


def get_document_for_user(db: Session, document_id: str, user_id: str) -> Document | None:
    statement = (
        select(Document)
        .options(selectinload(Document.ingestion_job), selectinload(Document.folder))
        .where(Document.id == document_id)
    )
    return db.scalar(apply_document_visibility(statement, user_id))


def get_owned_document_for_user(db: Session, document_id: str, user_id: str) -> Document | None:
    statement = (
        select(Document)
        .options(selectinload(Document.ingestion_job), selectinload(Document.folder))
        .where(Document.id == document_id, Document.user_id == user_id)
    )
    return db.scalar(statement)


def delete_document_for_user(db: Session, document_id: str, user_id: str) -> None:
    document = get_owned_document_for_user(db, document_id, user_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    active_status = document.ingestion_job.status if document.ingestion_job is not None else document.status
    if active_status in RUNNING_INGESTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document cannot be deleted while processing is in progress",
        )

    storage_paths = {document.storage_path, document.pending_storage_path}
    db.delete(document)
    db.commit()

    for storage_path in storage_paths:
        remove_uploaded_file(storage_path)


def move_document_for_user(db: Session, document_id: str, user_id: str, payload: DocumentMoveRequest) -> Document:
    document = get_owned_document_for_user(db, document_id, user_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    target_folder = get_document_target_folder(db, folder_id=str(payload.folder_id) if payload.folder_id else None, user_id=user_id)
    document.folder_id = target_folder.id if target_folder else None
    db.commit()
    refreshed = get_document_for_user(db, document_id, user_id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to reload moved document")
    return refreshed


def serialize_document_payload(document: Document) -> dict[str, Any]:
    return DocumentResponse.model_validate(document).model_dump(mode="json")


def format_document_status_sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def stream_document_status(document_id: str, user_id: str, *, poll_interval_seconds: float = 1.0):
    with SessionLocal() as db:
        bind_current_user_context(db, user_id)
        previous_payload: str | None = None

        while True:
            document = get_document_for_user(db, document_id, user_id)
            if document is None:
                yield format_document_status_sse(
                    "error",
                    {
                        "detail": "Document not found",
                        "documentId": document_id,
                    },
                )
                return

            payload = {"document": serialize_document_payload(document)}
            serialized_payload = json.dumps(payload, sort_keys=True)
            if serialized_payload != previous_payload:
                yield format_document_status_sse("document", payload)
                previous_payload = serialized_payload

            ingestion_job = document.ingestion_job
            if ingestion_job is not None and ingestion_job.status in TERMINAL_INGESTION_STATUSES:
                yield format_document_status_sse("done", payload)
                return

            yield format_document_status_sse(
                "heartbeat",
                {
                    "documentId": document_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            time.sleep(poll_interval_seconds)
            db.expire_all()
