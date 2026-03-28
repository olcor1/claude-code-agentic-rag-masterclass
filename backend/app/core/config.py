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
    local_llm_base_url: str = ""
    local_llm_api_key: str = "local-dev-key"
    local_llm_model: str = ""
    llm_embed_url: str = "http://localhost:1234/v1"
    llm_embed_api_key: str = ""
    llm_embed_model: str = "local-embed-model"
    llm_embed_dimensions: int = 768
    pii_redaction_enabled: bool = False
    entity_resolution_mode: str = "algorithmic"
    pii_surrogate_entities: str = "PERSON,EMAIL_ADDRESS,PHONE_NUMBER,LOCATION,DATE_TIME,URL,IP_ADDRESS"
    pii_redact_entities: str = (
        "CREDIT_CARD,US_SSN,US_ITIN,US_BANK_NUMBER,IBAN_CODE,CRYPTO,US_PASSPORT,"
        "US_DRIVER_LICENSE,MEDICAL_LICENSE"
    )
    pii_surrogate_score_threshold: float = 0.7
    pii_redact_score_threshold: float = 0.3
    pii_missed_scan_enabled: bool = False
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
    def resolved_frontend_origins(self) -> list[str]:
        configured = [item.strip() for item in self.frontend_origin.split(",") if item.strip()]
        if not configured:
            configured = ["http://localhost:5173"]

        expanded = list(configured)
        if "http://localhost:5173" in configured and "http://127.0.0.1:5173" not in expanded:
            expanded.append("http://127.0.0.1:5173")
        if "http://127.0.0.1:5173" in configured and "http://localhost:5173" not in expanded:
            expanded.append("http://localhost:5173")
        return expanded

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
    def local_llm_configured(self) -> bool:
        return bool(self.local_llm_base_url.strip() and self.local_llm_model.strip())

    @property
    def resolved_local_llm_api_key(self) -> str:
        return self.local_llm_api_key or "local-dev-key"

    @property
    def resolved_pii_surrogate_entities(self) -> list[str]:
        return [item.strip().upper() for item in self.pii_surrogate_entities.split(",") if item.strip()]

    @property
    def resolved_pii_redact_entities(self) -> list[str]:
        return [item.strip().upper() for item in self.pii_redact_entities.split(",") if item.strip()]

    @property
    def normalized_entity_resolution_mode(self) -> str:
        mode = self.entity_resolution_mode.strip().lower()
        if mode in {"llm", "algorithmic", "none"}:
            return mode
        return "algorithmic"

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
