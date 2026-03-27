from typing import Any
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreateRequest(BaseModel):
    title: str | None = None


class MetadataFilters(BaseModel):
    document_types: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class StreamMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    metadata_filters: MetadataFilters | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    citations: list[dict] = Field(default_factory=list)
    agent_trace: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse] = Field(default_factory=list)
