from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.folder import FolderResponse


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    status: str
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExtractedMetadataResponse(BaseModel):
    title: str | None = None
    summary: str | None = None
    document_type: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    language: str | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    folder_id: UUID | None
    filename: str
    source_key: str
    storage_path: str
    content_hash: str | None
    hash_algorithm: str
    version: int
    last_ingestion_result: str | None
    extracted_metadata: ExtractedMetadataResponse | None = None
    metadata_schema_version: int | None
    metadata_status: str
    metadata_error: str | None
    metadata_extracted_at: datetime | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    folder: FolderResponse | None = None
    ingestion_job: IngestionJobResponse


class DocumentMoveRequest(BaseModel):
    folder_id: UUID | None = None


class DocumentStatusResponse(BaseModel):
    document_id: UUID
    ingestion_job_id: UUID
    status: str
    last_ingestion_result: str | None = None
    error_message: str | None = None
    metadata_status: str = "not_started"
    metadata_error: str | None = None
    metadata_extracted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None
