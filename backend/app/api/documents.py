from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models import Document
from app.db.session import get_db
from app.schemas.document import DocumentResponse, DocumentStatusResponse
from app.services.auth import get_current_user
from app.services.documents import list_documents_for_user, process_document, save_upload_file


router = APIRouter()


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> DocumentResponse:
    storage_path = save_upload_file(file)
    document = Document(
        user_id=user.id,
        filename=file.filename or storage_path.name,
        storage_path=str(storage_path),
        status="uploaded",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    background_tasks.add_task(process_document, str(document.id))
    return DocumentResponse.model_validate(document)


@router.get("", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_db), user=Depends(get_current_user)) -> list[DocumentResponse]:
    return [DocumentResponse.model_validate(item) for item in list_documents_for_user(db, str(user.id))]


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)) -> DocumentResponse:
    document = db.get(Document, document_id)
    if not document or str(document.user_id) != str(user.id):
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def get_document_status(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)) -> DocumentStatusResponse:
    document = db.get(Document, document_id)
    if not document or str(document.user_id) != str(user.id):
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentStatusResponse(id=document.id, status=document.status, error_message=document.error_message)
