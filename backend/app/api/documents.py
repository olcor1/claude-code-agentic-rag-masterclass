from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.document import DocumentMoveRequest, DocumentResponse, DocumentStatusResponse
from app.services.auth import get_current_user
from app.services.documents import (
    delete_document_for_user,
    get_document_for_user,
    list_documents_for_user,
    move_document_for_user,
    prepare_document_upload,
    process_document,
    remove_uploaded_file,
    save_upload_file,
    stream_document_status,
)


router = APIRouter()


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_key: str | None = Form(default=None),
    folder_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> DocumentResponse:
    storage_path = save_upload_file(file)
    try:
        document, should_queue = prepare_document_upload(
            db,
            user_id=str(user.id),
            filename=file.filename or storage_path.name,
            source_key=source_key,
            storage_path=str(storage_path),
            folder_id=folder_id,
        )
    except Exception:
        try:
            remove_uploaded_file(str(storage_path))
        except Exception:
            pass
        raise

    ingestion_job = document.ingestion_job
    if should_queue and ingestion_job is not None:
        background_tasks.add_task(process_document, str(document.id), str(ingestion_job.id), str(user.id))

    created_document = get_document_for_user(db, str(document.id), str(user.id))
    if created_document is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to reload created document")
    return DocumentResponse.model_validate(created_document)


@router.get("", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_db), user=Depends(get_current_user)) -> list[DocumentResponse]:
    return [DocumentResponse.model_validate(item) for item in list_documents_for_user(db, str(user.id))]


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)) -> DocumentResponse:
    document = get_document_for_user(db, document_id, str(user.id))
    if not document:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/status/stream")
def stream_document_updates(
    document_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> StreamingResponse:
    document = get_document_for_user(db, document_id, str(user.id))
    if not document:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    generator = stream_document_status(document_id, str(user.id))
    response = StreamingResponse(generator, media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def get_document_status(
    document_id: str,
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> DocumentStatusResponse:
    document = get_document_for_user(db, document_id, str(user.id))
    if not document:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.ingestion_job is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document is missing its ingestion job")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return DocumentStatusResponse(
        document_id=document.id,
        ingestion_job_id=document.ingestion_job.id,
        status=document.ingestion_job.status,
        last_ingestion_result=document.last_ingestion_result,
        error_message=document.ingestion_job.error_message,
        metadata_status=document.metadata_status,
        metadata_error=document.metadata_error,
        metadata_extracted_at=document.metadata_extracted_at,
        started_at=document.ingestion_job.started_at,
        completed_at=document.ingestion_job.completed_at,
        updated_at=document.ingestion_job.updated_at,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)) -> Response:
    delete_document_for_user(db, document_id, str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{document_id}/move", response_model=DocumentResponse)
def move_document(
    document_id: str,
    payload: DocumentMoveRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> DocumentResponse:
    document = move_document_for_user(db, document_id, str(user.id), payload)
    return DocumentResponse.model_validate(document)
