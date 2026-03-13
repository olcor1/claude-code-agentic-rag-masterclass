from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Agentic RAG Local"
    database_url: str = "postgresql+psycopg://rag_user:rag_password@localhost:55432/agentic_rag"
    jwt_secret: str = "change-me"
    jwt_expires_min: int = 1440
    frontend_origin: str = "http://localhost:5173"
    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "local-dev-key"
    llm_chat_model: str = "local-chat-model"
    llm_embed_model: str = "local-embed-model"
    llm_embed_dimensions: int = 768
    retrieval_limit: int = 4
    chunk_size: int = 1000
    chunk_overlap: int = 200
    uploads_dir: Path = Field(default_factory=lambda: BASE_DIR / "uploads")
    langsmith_api_key: str = ""
    langsmith_project: str = "agentic-rag-local"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @property
    def psycopg_database_url(self) -> str:
        return self.database_url.replace("+psycopg", "")

    @property
    def langsmith_enabled(self) -> bool:
        return bool(self.langsmith_api_key and self.langsmith_project)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
