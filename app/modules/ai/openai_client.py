"""The one OpenAI client the ai module shares: answer reading, speech to text, photo checks.

The settings decide which features call it (`LLM_PROVIDER`, `STT_PROVIDER`); this only builds
the client once per process from `OPENAI_API_KEY` (and `OPENAI_BASE_URL` for Azure or another
compatible endpoint). Short timeout and one retry: these calls sit in the chat's path.
"""

import openai

from app.core.config import settings

_client: openai.AsyncOpenAI | None = None


def get_client() -> openai.AsyncOpenAI | None:
    """The shared client, or None when no API key is set."""
    global _client
    if not settings.openai_api_key:
        return None
    if _client is None:
        _client = openai.AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        )
    return _client
