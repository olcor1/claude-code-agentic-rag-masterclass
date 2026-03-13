from openai import OpenAI

from app.core.config import settings
from app.services.tracing import traceable


client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


@traceable(name="embed-texts", run_type="tool")
def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    response = client.embeddings.create(model=settings.llm_embed_model, input=texts)
    return [item.embedding for item in response.data]
