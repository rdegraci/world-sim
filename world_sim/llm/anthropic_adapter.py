"""Anthropic Messages API adapter."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from anthropic import Anthropic

from world_sim.llm.base import ChatMessage, LLMResponse, ToolCall
from world_sim.utils.logger import get_logger

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"


class AnthropicAdapter:
    """Anthropic-backed LLM adapter behind the shared responses-style interface."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_ANTHROPIC_MODEL,
    ) -> None:
        if not api_key:
            raise ValueError("AnthropicAdapter requires a non-empty api_key.")
        self.model = model
        self._client = Anthropic(api_key=api_key)
        self._logger = get_logger("llm.anthropic")

    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        anthropic_messages: list[dict[str, Any]] = [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.role in {"user", "assistant"}
        ]
        if not anthropic_messages:
            anthropic_messages = [{"role": "user", "content": ""}]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system,
            "messages": anthropic_messages,
        }
        if tools:
            converted = []
            for tool in tools:
                function = tool.get("function", tool)
                converted.append(
                    {
                        "name": function["name"],
                        "description": function.get("description", ""),
                        "input_schema": function.get(
                            "parameters",
                            {"type": "object", "properties": {}},
                        ),
                    }
                )
            kwargs["tools"] = converted

        self._logger.info(
            "Calling Anthropic model=%s tools=%s",
            self.model,
            bool(tools),
        )
        response = self._client.messages.create(**kwargs)
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif block_type == "tool_use":
                raw_input = getattr(block, "input", {}) or {}
                if not isinstance(raw_input, dict):
                    try:
                        raw_input = json.loads(str(raw_input))
                    except json.JSONDecodeError:
                        raw_input = {}
                tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", None) or str(uuid4()),
                        name=getattr(block, "name", "unknown"),
                        arguments=raw_input if isinstance(raw_input, dict) else {},
                    )
                )
        return LLMResponse(text="".join(text_parts), tool_calls=tool_calls)
