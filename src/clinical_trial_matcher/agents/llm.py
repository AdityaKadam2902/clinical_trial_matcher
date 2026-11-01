"""Provider-aware LLM clients for the agent pipeline.

The pipeline must never send patient data to a third party in production.
``settings.llm_provider`` selects between a local OpenAI-compatible endpoint
(Ollama/vLLM) and the explicit Groq development fallback. Keeping the
selection here means agents do not each re-implement provider logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import dspy
import httpx
from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq

from clinical_trial_matcher.core.config import settings


@dataclass(slots=True)
class ChatResponse:
    """Minimal LangChain-compatible response for the local HTTP client."""

    content: str


class LocalChatModel:
    """Small async/sync client for an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = httpx.Timeout(settings.local_llm_timeout_seconds, connect=10.0)

    def _payload(self, messages: Sequence[BaseMessage]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": _role_for(message), "content": _content_for(message)} for message in messages],
            "temperature": self._temperature,
            "stream": False,
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        return payload

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def invoke(self, messages: Sequence[BaseMessage]) -> ChatResponse:
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(self._url, headers=self._headers, json=self._payload(messages))
            response.raise_for_status()
            return ChatResponse(_extract_content(response.json()))

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> ChatResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, headers=self._headers, json=self._payload(messages))
            response.raise_for_status()
            return ChatResponse(_extract_content(response.json()))


def _role_for(message: BaseMessage) -> str:
    role = message.type
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    if role == "system":
        return "system"
    return "user"


def _content_for(message: BaseMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else str(content)


def _extract_content(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Local LLM returned an unexpected response shape") from exc
    return content if isinstance(content, str) else str(content)


def _build_chat_model(
    *,
    model: str,
    temperature: float,
    max_tokens: int | None = None,
) -> ChatGroq | LocalChatModel:
    if settings.llm_provider == "groq":
        return ChatGroq(
            api_key=settings.groq_api_key.get_secret_value(),
            model_name=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    return LocalChatModel(
        base_url=settings.local_llm_base_url,
        api_key=settings.local_llm_api_key.get_secret_value(),
        model=settings.local_llm_model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


@lru_cache(maxsize=1)
def get_fast_chat_model() -> ChatGroq | LocalChatModel:
    """Model for extraction tasks (profile parsing)."""
    model = settings.groq_model_fast if settings.llm_provider == "groq" else settings.local_llm_model
    return _build_chat_model(model=model, temperature=0.0)


@lru_cache(maxsize=1)
def get_complex_chat_model() -> ChatGroq | LocalChatModel:
    """Model for physician-facing generation tasks."""
    model = settings.groq_model_complex if settings.llm_provider == "groq" else settings.local_llm_model
    return _build_chat_model(model=model, temperature=0.1, max_tokens=1500)


@lru_cache(maxsize=1)
def get_dspy_lm() -> dspy.LM:
    """DSPy LM honouring the configured provider.

    DSPy delegates to LiteLLM. ``openai/<model>`` plus ``api_base`` targets an
    OpenAI-compatible local server, while ``groq/<model>`` targets Groq.
    """
    if settings.llm_provider == "groq":
        return dspy.LM(
            model=f"groq/{settings.groq_model_complex}",
            api_key=settings.groq_api_key.get_secret_value(),
            temperature=0.0,
            max_tokens=1200,
            timeout=settings.eligibility_timeout_seconds,
            num_retries=0,
        )
    return dspy.LM(
        model=f"openai/{settings.local_llm_model}",
        api_base=settings.local_llm_base_url,
        api_key=settings.local_llm_api_key.get_secret_value(),
        temperature=0.0,
        max_tokens=1200,
        timeout=settings.eligibility_timeout_seconds,
        num_retries=0,
    )
