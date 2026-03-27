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
    database_app_role: str = "rag_app"
    jwt_secret: str = "change-me"
    jwt_expires_min: int = 1440
    frontend_origin: str = "http://localhost:5173"
    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "local-dev-key"
    llm_chat_model: str = "local-chat-model"
    llm_metadata_model: str = ""
    llm_embed_url: str = "http://localhost:1234/v1"
    llm_embed_api_key: str = ""
    llm_embed_model: str = "local-embed-model"
    llm_embed_dimensions: int = 768
    retrieval_limit: int = 4
    retrieval_vector_limit: int = 8
    retrieval_keyword_limit: int = 8
    retrieval_candidate_limit: int = 8
    retrieval_rrf_k: int = 60
    retrieval_max_distance: float = 0.45
    sql_tool_row_limit: int = 8
    chunk_size: int = 1000
    chunk_overlap: int = 200
    pdf_ocr_enabled: bool = True
    pdf_ocr_engine: str = "tesseract_cli"
    pdf_ocr_languages: str = "fra,eng"
    pdf_force_full_page_ocr: bool = True
    pdf_ocr_min_chars: int = 80
    uploads_dir: Path = Field(default_factory=lambda: BASE_DIR / "uploads")
    web_search_enabled: bool = True
    web_search_provider: str = "duckduckgo_html"
    web_search_api_key: str = ""
    web_search_max_results: int = 3
    web_search_timeout_seconds: float = 10.0
    web_search_user_agent: str = "AgenticRAGLocal/1.0"
    langsmith_api_key: str = ""
    langsmith_project: str = "agentic-rag-local"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @property
    def psycopg_database_url(self) -> str:
        return self.database_url.replace("+psycopg", "")

    @property
    def resolved_llm_embed_api_key(self) -> str:
        return self.llm_embed_api_key or self.llm_api_key

    @property
    def resolved_llm_metadata_model(self) -> str:
        return self.llm_metadata_model or self.llm_chat_model

    @property
    def resolved_pdf_ocr_languages(self) -> list[str]:
        return [item.strip() for item in self.pdf_ocr_languages.split(",") if item.strip()]

    @property
    def langsmith_enabled(self) -> bool:
        return bool(self.langsmith_api_key and self.langsmith_project)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
