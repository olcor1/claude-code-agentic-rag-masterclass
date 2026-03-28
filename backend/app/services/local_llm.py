from functools import lru_cache

from openai import OpenAI

from app.core.config import settings


@lru_cache
def get_local_llm_client() -> OpenAI | None:
    if not settings.local_llm_configured:
        return None
    return OpenAI(
        base_url=settings.local_llm_base_url,
        api_key=settings.resolved_local_llm_api_key,
    )


def get_local_llm_model() -> str | None:
    if not settings.local_llm_configured:
        return None
    return settings.local_llm_model.strip() or None
