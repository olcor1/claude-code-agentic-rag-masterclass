from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Document, DocumentChunk, Folder
from app.services.folders import visible_document_clause, visible_folder_clause


EXPLORER_HINT_PATTERN = re.compile(
    r"\b("
    r"ls|tree|grep|glob|read|folder|folders|path|paths|directory|directories|"
    r"file name|filename|file names|browse|explore|under |inside |where is|where are|"
    r"which file|which folder|list files|show files|show me the structure|knowledge base structure"
    r")\b",
    re.IGNORECASE,
)
WILDCARD_PATTERN = re.compile(r"[*?\[\]]")
ROOT_SCOPES = ("global", "private")


@dataclass(slots=True)
class ResolvedPath:
    scope: str | None
    folder: Folder | None
    path: str


def looks_like_explorer_request(question: str) -> bool:
    normalized = " ".join(question.lower().split())
    return bool(EXPLORER_HINT_PATTERN.search(normalized) or WILDCARD_PATTERN.search(question))


def normalize_kb_path(path: str | None) -> str:
    raw = (path or "/").strip().replace("\\", "/")
    if not raw:
        return "/"
    if not raw.startswith("/"):
        raw = f"/{raw}"
    raw = re.sub(r"/{2,}", "/", raw)
    if raw != "/" and raw.endswith("/"):
        raw = raw.rstrip("/")
    return raw or "/"


def list_visible_folders(db: Session, user_id: UUID | str) -> list[Folder]:
    statement = select(Folder).where(visible_folder_clause(user_id)).order_by(Folder.scope.asc(), Folder.name.asc())
    return list(db.scalars(statement))


def list_visible_documents(db: Session, user_id: UUID | str) -> list[Document]:
    statement = (
        select(Document)
        .options(selectinload(Document.folder), selectinload(Document.ingestion_job))
        .where(visible_document_clause(user_id))
        .order_by(Document.filename.asc())
    )
    return list(db.scalars(statement))


def build_folder_path(folder: Folder, folders_by_id: dict[UUID, Folder]) -> str:
    segments = [folder.name]
    current = folder
    while current.parent_id:
        current = folders_by_id[current.parent_id]
        segments.append(current.name)
    segments.reverse()
    return f"/{folder.scope}/" + "/".join(segments)


def build_document_path(document: Document, folders_by_id: dict[UUID, Folder]) -> str:
    if document.folder_id and document.folder_id in folders_by_id:
        return f"{build_folder_path(folders_by_id[document.folder_id], folders_by_id)}/{document.filename}"
    return f"/private/{document.filename}"


def resolve_path(path: str | None, folders: list[Folder], user_id: UUID | str) -> ResolvedPath:
    normalized = normalize_kb_path(path)
    if normalized == "/":
        return ResolvedPath(scope=None, folder=None, path=normalized)

    segments = [segment for segment in normalized.split("/") if segment]
    scope = segments[0]
    if scope not in ROOT_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge-base paths must start with /global or /private",
        )

    parent_id: UUID | None = None
    current: Folder | None = None
    for segment in segments[1:]:
        matches = [
            item
            for item in folders
            if item.scope == scope
            and item.parent_id == parent_id
            and item.name == segment
            and (scope == "global" or str(item.user_id) == str(user_id))
        ]
        if not matches:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Folder path not found: {normalized}")
        current = matches[0]
        parent_id = current.id

    return ResolvedPath(scope=scope, folder=current, path=normalized)


def load_document_text(db: Session, document: Document) -> str:
    if document.full_markdown:
        return document.full_markdown

    statement = (
        select(DocumentChunk.content)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    parts = list(db.execute(statement).scalars())
    return "\n\n".join(parts)


def filter_documents_for_target(
    documents: list[Document],
    folders_by_id: dict[UUID, Folder],
    target: ResolvedPath,
) -> list[Document]:
    if target.scope is None:
        return []

    if target.folder is None:
        if target.scope == "global":
            return [document for document in documents if document.folder_id and document.folder and document.folder.scope == "global"]
        return [
            document
            for document in documents
            if document.folder_id is None or (document.folder and document.folder.scope == "private")
        ]

    prefix = target.path
    return [
        document
        for document in documents
        if build_document_path(document, folders_by_id) == prefix
        or build_document_path(document, folders_by_id).startswith(f"{prefix}/")
    ]


def match_glob_pattern(pattern: str, *, full_path: str, relative_path: str, filename: str) -> bool:
    normalized_pattern = pattern.lstrip("/")
    candidates = {
        full_path.lstrip("/"),
        relative_path.lstrip("/"),
        filename,
    }
    return any(PurePosixPath(candidate).match(normalized_pattern) for candidate in candidates)


def execute_ls(db: Session, user_id: UUID | str, path: str | None = None) -> dict[str, Any]:
    folders = list_visible_folders(db, user_id)
    documents = list_visible_documents(db, user_id)
    folders_by_id = {folder.id: folder for folder in folders}
    target = resolve_path(path, folders, user_id)

    if target.scope is None:
        return {
            "path": "/",
            "entries": [
                {"kind": "folder", "name": "global", "path": "/global", "scope": "global"},
                {"kind": "folder", "name": "private", "path": "/private", "scope": "private"},
            ],
        }

    child_parent_id = target.folder.id if target.folder else None
    child_folders = [
        folder
        for folder in folders
        if folder.scope == target.scope
        and folder.parent_id == child_parent_id
        and (target.scope == "global" or str(folder.user_id) == str(user_id))
    ]
    child_documents = [
        document
        for document in documents
        if (document.folder_id == child_parent_id)
        or (
            child_parent_id is None
            and target.scope == "private"
            and document.folder_id is None
            and str(document.user_id) == str(user_id)
        )
    ]

    entries = [
        {
            "kind": "folder",
            "name": folder.name,
            "path": build_folder_path(folder, folders_by_id),
            "scope": folder.scope,
            "folderId": str(folder.id),
        }
        for folder in sorted(child_folders, key=lambda item: item.name.lower())
    ]
    entries.extend(
        {
            "kind": "document",
            "name": document.filename,
            "path": build_document_path(document, folders_by_id),
            "documentId": str(document.id),
            "status": document.status,
        }
        for document in sorted(child_documents, key=lambda item: item.filename.lower())
    )

    return {"path": target.path, "entries": entries}


def execute_tree(
    db: Session,
    user_id: UUID | str,
    path: str | None = None,
    *,
    depth: int = 3,
    limit: int = 80,
) -> dict[str, Any]:
    folders = list_visible_folders(db, user_id)
    documents = list_visible_documents(db, user_id)
    folders_by_id = {folder.id: folder for folder in folders}
    target = resolve_path(path, folders, user_id)
    lines: list[str] = []
    truncated = False

    def append_line(line: str) -> bool:
        nonlocal truncated
        if len(lines) >= limit:
            truncated = True
            return False
        lines.append(line)
        return True

    def walk_scope(scope: str, current_folder: Folder | None, current_depth: int) -> None:
        if current_depth > depth:
            return

        child_parent_id = current_folder.id if current_folder else None
        child_folders = [
            folder
            for folder in folders
            if folder.scope == scope
            and folder.parent_id == child_parent_id
            and (scope == "global" or str(folder.user_id) == str(user_id))
        ]
        child_documents = [
            document
            for document in documents
            if (document.folder_id == child_parent_id)
            or (
                child_parent_id is None
                and scope == "private"
                and document.folder_id is None
                and str(document.user_id) == str(user_id)
            )
        ]

        indent = "  " * current_depth
        for folder in sorted(child_folders, key=lambda item: item.name.lower()):
            if not append_line(f"{indent}{folder.name}/"):
                return
            walk_scope(scope, folder, current_depth + 1)
            if truncated:
                return

        for document in sorted(child_documents, key=lambda item: item.filename.lower()):
            if not append_line(f"{indent}{document.filename}"):
                return

    if target.scope is None:
        append_line("/global")
        walk_scope("global", None, 1)
        if not truncated:
            append_line("/private")
            walk_scope("private", None, 1)
    elif target.folder is None:
        append_line(target.path)
        walk_scope(target.scope, None, 1)
    else:
        append_line(target.path)
        walk_scope(target.scope, target.folder, 1)

    return {
        "path": target.path,
        "depth": depth,
        "limit": limit,
        "truncated": truncated,
        "output": "\n".join(lines),
    }


def execute_grep(
    db: Session,
    user_id: UUID | str,
    pattern: str,
    path: str | None = None,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    folders = list_visible_folders(db, user_id)
    documents = [document for document in list_visible_documents(db, user_id) if document.status == "completed"]
    folders_by_id = {folder.id: folder for folder in folders}
    target = resolve_path(path, folders, user_id)
    target_documents = filter_documents_for_target(documents, folders_by_id, target)

    try:
        regex = re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid regex pattern: {exc}") from exc

    matches: list[dict[str, Any]] = []
    for document in target_documents:
        text = load_document_text(db, document)
        if not text:
            continue
        line_hits = [index for index, line in enumerate(text.splitlines(), start=1) if regex.search(line)]
        if not line_hits:
            continue
        matches.append(
            {
                "documentId": str(document.id),
                "filename": document.filename,
                "path": build_document_path(document, folders_by_id),
                "matchCount": len(line_hits),
                "lineNumbers": line_hits[:5],
            }
        )
        if len(matches) >= limit:
            break

    return {
        "pattern": pattern,
        "path": target.path,
        "matches": matches,
    }


def execute_glob(
    db: Session,
    user_id: UUID | str,
    pattern: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    folders = list_visible_folders(db, user_id)
    documents = list_visible_documents(db, user_id)
    folders_by_id = {folder.id: folder for folder in folders}

    matches: list[dict[str, Any]] = []
    for document in documents:
        full_path = build_document_path(document, folders_by_id)
        relative_path = full_path.split("/", maxsplit=2)[-1] if full_path.count("/") >= 2 else document.filename
        if not match_glob_pattern(pattern, full_path=full_path, relative_path=relative_path, filename=document.filename):
            continue
        matches.append(
            {
                "documentId": str(document.id),
                "filename": document.filename,
                "path": full_path,
                "status": document.status,
            }
        )
        if len(matches) >= limit:
            break

    return {
        "pattern": pattern,
        "matches": matches,
    }


def execute_read(
    db: Session,
    user_id: UUID | str,
    document_id: UUID | str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    statement = (
        select(Document)
        .options(selectinload(Document.folder))
        .where(Document.id == document_id, visible_document_clause(user_id), Document.status == "completed")
    )
    document = db.scalar(statement)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    folders = list_visible_folders(db, user_id)
    folders_by_id = {folder.id: folder for folder in folders}
    content = load_document_text(db, document)
    lines = content.splitlines()
    total_lines = max(len(lines), 1)
    start = start_line or 1
    end = end_line or len(lines)
    if start < 1 or end < start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid line range")

    selected_lines = lines[start - 1 : end]
    return {
        "documentId": str(document.id),
        "filename": document.filename,
        "path": build_document_path(document, folders_by_id),
        "startLine": start,
        "endLine": min(end, total_lines),
        "totalLines": total_lines,
        "content": "\n".join(selected_lines) if selected_lines else "",
    }
