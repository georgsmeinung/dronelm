"""LM Studio / OpenAI-compatible client used by the planner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - optional at import time
    OpenAI = None  # type: ignore

from ..config import Settings, get_settings


@dataclass(frozen=True)
class PlannerResponse:
    """The result of one planner completion."""

    content: str
    raw: Any


class LMStudioClient:
    """Thin wrapper over the OpenAI SDK for an LM Studio / Ollama server.

    The same class can be configured for either the ground planner or the
    tactical SLM (different ``base_url`` / ``model``).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        self._base_url = base_url or cfg.lmstudio_base_url
        self._api_key = api_key or cfg.lmstudio_api_key
        self._model = model or cfg.lmstudio_model
        self._settings = cfg
        self._client: Any = None

    # ------------------------------------------------------------------ #
    # OpenAI client (lazy)                                              #
    # ------------------------------------------------------------------ #
    @property
    def client(self) -> Any:
        if self._client is None:
            if OpenAI is None:
                raise RuntimeError(
                    "openai SDK not available. `pip install openai` to enable LLM calls."
                )
            self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._client

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------ #
    # Completions                                                       #
    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> PlannerResponse:
        """Issue a chat completion and return the first choice's content."""
        temperature = (
            float(temperature)
            if temperature is not None
            else float(self._settings.planner_temperature)
        )
        max_tokens = (
            int(max_tokens)
            if max_tokens is not None
            else int(self._settings.planner_max_tokens)
        )
        completion = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = ""
        try:
            content = completion.choices[0].message.content or ""
        except Exception:
            content = ""
        return PlannerResponse(content=content, raw=completion)


class PlannerLLM:
    """High-level helper that exposes :meth:`complete_json` for the planner.

    It owns the system prompt + user message and forwards to the LM Studio
    client. The caller decides how to coerce the response (we let
    :func:`extract_json_object` live outside to keep the client testable).
    """

    def __init__(
        self,
        system_prompt: str,
        client: Optional[LMStudioClient] = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._client = client or LMStudioClient()

    @property
    def client(self) -> LMStudioClient:
        return self._client

    def complete(self, user_prompt: str, **kwargs: Any) -> PlannerResponse:
        """Run a chat completion with the configured system prompt."""
        return self._client.chat(
            [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **kwargs,
        )
