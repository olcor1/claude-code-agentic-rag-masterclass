from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    filename: str
    storage_path: str
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentStatusResponse(BaseModel):
    id: UUID
    status: str
    error_message: str | None = None
