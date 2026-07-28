"""Grok (xAI) adapter using an OpenAI-compatible chat completions API."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from openai import OpenAI

from world_sim.llm.base import ChatMessage, LLMResponse, ToolCall
from world_sim.utils.logger import get_logger

DEFAULT_GROK_BASE_URL = "https://api.x.ai/v1"
DEFAULT_GROK_MODEL = "grok-4.5"


class GrokAdapter:
    """Grok-backed LLM adapter for Slice 3 play."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_GROK_MODEL,
        base_url: str = DEFAULT_GROK_BASE_URL,
    ) -> None:
        if not api_key:
            raise ValueError("GrokAdapter requires a non-empty api_key.")
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._logger = get_logger("llm.grok")

    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        payload_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system}
        ]
        payload_messages.extend(
            {"role": message.role, "content": message.content} for message in messages
        )
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        self._logger.info("Calling Grok model=%s tools=%s", self.model, bool(tools))
        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0].message
        text = choice.content or ""
        tool_calls: list[ToolCall] = []
        for call in choice.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append(
                ToolCall(
                    id=call.id or str(uuid4()),
                    name=call.function.name,
                    arguments=arguments,
                )
            )
        return LLMResponse(text=text, tool_calls=tool_calls)
