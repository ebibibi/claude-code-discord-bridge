"""AI Foundry 呼出サービス。gateway の ClaudeService を参考にした共通AI呼出。"""

from __future__ import annotations

import httpx
from azure.core.credentials import TokenCredential

_ANTHROPIC_VERSION = "2023-06-01"
_SCOPE = "https://cognitiveservices.azure.com/.default"


class AIService:
    def __init__(
        self,
        endpoint: str,
        credential: TokenCredential,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/") + "/anthropic/v1/messages"
        self._credential = credential
        self._timeout = timeout_seconds

    async def invoke(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 8192,
    ) -> tuple[str, dict[str, int]]:
        token = self._credential.get_token(_SCOPE).token
        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._endpoint, headers=headers, json=body)

        if response.status_code == 429:
            raise RuntimeError("AI API rate limit exceeded")
        if response.status_code >= 400:
            raise RuntimeError(f"AI API error: {response.status_code} - {response.text[:200]}")

        data = response.json()
        text = data["content"][0]["text"]
        usage = {
            "input_tokens": data["usage"]["input_tokens"],
            "output_tokens": data["usage"]["output_tokens"],
        }
        return text, usage
