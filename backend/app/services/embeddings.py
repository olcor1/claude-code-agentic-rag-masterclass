from openai import APIConnectionError, APIStatusError, NotFoundError, OpenAI

from app.core.config import settings
from app.services.tracing import traceable


embed_client = OpenAI(base_url=settings.llm_embed_url, api_key=settings.resolved_llm_embed_api_key)


class EmbeddingProviderError(RuntimeError):
    """Raised when the configured embedding provider cannot serve requests."""


def _format_embedding_provider_error(exc: Exception) -> str:
    endpoint = settings.llm_embed_url.rstrip("/")
    model = settings.llm_embed_model
    if isinstance(exc, APIConnectionError):
        return (
            f"Embedding provider unavailable at {endpoint} for model {model}. "
            "Start the local embedding server or update LLM_EMBED_URL / LLM_EMBED_MODEL."
        )
    if isinstance(exc, NotFoundError):
        return (
            f"Embedding model {model} was not found at {endpoint}. "
            "Load or pull that model, then retry ingestion."
        )
    if isinstance(exc, APIStatusError):
        return f"Embedding request failed with status {exc.status_code} at {endpoint} for model {model}."
    return str(exc)


@traceable(name="embed-texts", run_type="tool")
def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    try:
        response = embed_client.embeddings.create(model=settings.llm_embed_model, input=texts)
    except (APIConnectionError, NotFoundError, APIStatusError) as exc:
        raise EmbeddingProviderError(_format_embedding_provider_error(exc)) from exc
    return [item.embedding for item in response.data]
