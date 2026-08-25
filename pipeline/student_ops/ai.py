"""Minimal, safe OpenAI-compatible adapter plus reproducible fixture adapter."""
from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIAdapterError(RuntimeError):
    """Safe error category only; never include response content, tokens, or keys."""


class FixtureAIAdapter:
    mode = "fixture"

    def generate(self, *, system: str, user: str, fixture_response: str | None = None) -> str:
        if not fixture_response:
            raise AIAdapterError("fixture_response_missing")
        return fixture_response


class OpenAICompatibleAdapter:
    mode = "live"

    def __init__(self, api_key: str, base_url: str, model: str, transport: Callable[[Request], bytes] | None = None):
        if not api_key or not base_url or not model:
            raise AIAdapterError("ai_configuration_missing")
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.transport = transport or self._urlopen_transport

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleAdapter":
        return cls(os.environ.get("AI_API_KEY", ""), os.environ.get("AI_BASE_URL", ""), os.environ.get("AI_MODEL", ""))

    def _urlopen_transport(self, request: Request) -> bytes:
        with urlopen(request, timeout=45) as response:  # nosec B310: explicit configured endpoint
            return response.read()

    def generate(self, *, system: str, user: str, fixture_response: str | None = None) -> str:
        endpoint = self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"
        body = json.dumps({"model": self.model, "temperature": 0, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, ensure_ascii=False).encode("utf-8")
        request = Request(endpoint, data=body, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            response = json.loads(self.transport(request).decode("utf-8"))
            content = response["choices"][0]["message"]["content"]
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError):
            raise AIAdapterError("ai_request_failed") from None
        if not isinstance(content, str) or not content.strip():
            raise AIAdapterError("ai_response_invalid")
        return content.strip()
