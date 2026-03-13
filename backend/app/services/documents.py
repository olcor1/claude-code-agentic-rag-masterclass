import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal
from app.services.embeddings import embed_texts
from app.services.tracing import traceable
from app.utils.text import chunk_text


def save_upload_file(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".txt", ".md"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .txt and .md files are supported")

    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4()}-{Path(upload.filename or 'upload').name}"
    destination = settings.uploads_dir / safe_name
    with destination.open("wb") as target:
        while chunk := upload.file.read(1024 * 1024):
            target.write(chunk)
    return destination


def read_document_text(storage_path: str) -> str:
    path = Path(storage_path)
    if not path.exists():
        raise FileNotFoundError(storage_path)
    return path.read_text(encoding="utf-8")


@traceable(name="process-document", run_type="chain")
def process_document(document_id: str) -> None:
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document:
            return

        document.status = "processing"
        document.error_message = None
        db.commit()

        try:
            content = read_document_text(document.storage_path)
            chunks = chunk_text(content, settings.chunk_size, settings.chunk_overlap)
            embeddings = embed_texts(chunks)

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

            document.status = "processed"
            db.commit()
        except Exception as exc:  # pragma: no cover - background task error path
            document.status = "failed"
            document.error_message = str(exc)
            db.commit()


def list_documents_for_user(db: Session, user_id: str) -> list[Document]:
    statement = select(Document).where(Document.user_id == user_id).order_by(Document.created_at.desc())
    return list(db.scalars(statement))
