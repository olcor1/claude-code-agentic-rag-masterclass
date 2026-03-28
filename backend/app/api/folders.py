from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.folder import FolderCreateRequest, FolderResponse, FolderUpdateRequest
from app.services.auth import get_current_user
from app.services.folders import create_folder_for_user, delete_folder_for_user, list_folders_for_user, update_folder_for_user


router = APIRouter()


@router.get("", response_model=list[FolderResponse])
def get_folders(db: Session = Depends(get_db), user=Depends(get_current_user)) -> list[FolderResponse]:
    return [FolderResponse.model_validate(item) for item in list_folders_for_user(db, user.id)]


@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
def post_folder(
    payload: FolderCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> FolderResponse:
    folder = create_folder_for_user(
        db,
        user_id=user.id,
        name=payload.name,
        scope=payload.scope,
        parent_id=payload.parent_id,
    )
    return FolderResponse.model_validate(folder)


@router.patch("/{folder_id}", response_model=FolderResponse)
def patch_folder(
    folder_id: str,
    payload: FolderUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> FolderResponse:
    folder = update_folder_for_user(
        db,
        folder_id=folder_id,
        user_id=user.id,
        name=payload.name if "name" in payload.model_fields_set else None,
        parent_id=payload.parent_id,
        update_parent="parent_id" in payload.model_fields_set,
    )
    return FolderResponse.model_validate(folder)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(folder_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)) -> Response:
    delete_folder_for_user(db, folder_id=folder_id, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
