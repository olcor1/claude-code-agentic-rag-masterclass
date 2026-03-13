import logging
import os
from functools import wraps
from typing import Any, Callable, TypeVar

from app.core.config import settings


logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])

try:
    from langsmith import traceable as _traceable
except Exception:  # pragma: no cover - fallback when dependency is missing
    _traceable = None


def configure_langsmith() -> None:
    if settings.langsmith_enabled:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
        os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        logger.info("LangSmith tracing enabled for project %s", settings.langsmith_project)
    else:
        logger.info("LangSmith tracing disabled")


def traceable(name: str, run_type: str = "chain") -> Callable[[F], F]:
    def decorator(func: F) -> F:
        if _traceable and settings.langsmith_enabled:
            return _traceable(name=name, run_type=run_type)(func)

        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any):
            return func(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator
