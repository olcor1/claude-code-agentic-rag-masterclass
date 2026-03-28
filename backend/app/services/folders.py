from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Document, Folder


def visible_folder_clause(user_id: UUID | str):
    return or_(Folder.user_id == user_id, Folder.scope == "global")


def visible_document_clause(user_id: UUID | str):
    return or_(Document.user_id == user_id, Document.folder.has(Folder.scope == "global"))


def normalize_folder_name(name: str) -> str:
    cleaned = " ".join(name.split()).strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder name cannot be empty")
    return cleaned[:255]


def list_folders_for_user(db: Session, user_id: UUID | str) -> list[Folder]:
    statement = select(Folder).where(visible_folder_clause(user_id)).order_by(Folder.scope.asc(), Folder.name.asc())
    return list(db.scalars(statement))


def get_folder_for_user(db: Session, folder_id: UUID | str, user_id: UUID | str) -> Folder | None:
    statement = select(Folder).where(Folder.id == folder_id, visible_folder_clause(user_id))
    return db.scalar(statement)


def get_owned_folder_for_user(db: Session, folder_id: UUID | str, user_id: UUID | str) -> Folder | None:
    statement = select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
    return db.scalar(statement)


def get_optional_parent_for_write(
    db: Session,
    *,
    parent_id: UUID | str | None,
    user_id: UUID | str,
    expected_scope: str | None = None,
) -> Folder | None:
    if parent_id is None:
        return None

    parent = get_owned_folder_for_user(db, parent_id, user_id)
    if parent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent folder not found")
    if expected_scope and parent.scope != expected_scope:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Folder scope must match its parent folder scope",
        )
    return parent


def get_document_target_folder(
    db: Session,
    *,
    folder_id: UUID | str | None,
    user_id: UUID | str,
) -> Folder | None:
    if folder_id is None:
        return None

    folder = get_folder_for_user(db, folder_id, user_id)
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    if folder.scope == "private" and str(folder.user_id) != str(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Private folder is not writable")
    return folder


def create_folder_for_user(
    db: Session,
    *,
    user_id: UUID | str,
    name: str,
    scope: str,
    parent_id: UUID | str | None,
) -> Folder:
    parent = get_optional_parent_for_write(db, parent_id=parent_id, user_id=user_id, expected_scope=scope)
    folder = Folder(
        user_id=user_id,
        name=normalize_folder_name(name),
        scope=scope,
        parent_id=parent.id if parent else None,
    )
    db.add(folder)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Folder already exists in that location") from exc
    db.refresh(folder)
    return folder


def update_folder_for_user(
    db: Session,
    *,
    folder_id: UUID | str,
    user_id: UUID | str,
    name: str | None = None,
    parent_id: UUID | str | None = None,
    update_parent: bool = False,
) -> Folder:
    folder = get_owned_folder_for_user(db, folder_id, user_id)
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    if name is not None:
        folder.name = normalize_folder_name(name)

    if update_parent:
        parent = get_optional_parent_for_write(db, parent_id=parent_id, user_id=user_id, expected_scope=folder.scope)
        if parent and parent.id == folder.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Folder cannot be moved into itself")
        folder.parent_id = parent.id if parent else None

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Folder update would create a conflict or invalid hierarchy",
        ) from exc
    db.refresh(folder)
    return folder


def delete_folder_for_user(db: Session, *, folder_id: UUID | str, user_id: UUID | str) -> None:
    folder = get_owned_folder_for_user(db, folder_id, user_id)
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    db.delete(folder)
    db.commit()


def apply_document_visibility(statement: Select, user_id: UUID | str):
    return statement.where(visible_document_clause(user_id))
