from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router


api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(conversations_router, prefix="/conversations", tags=["conversations"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
