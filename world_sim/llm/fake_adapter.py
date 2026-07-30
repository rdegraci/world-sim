"""Deterministic offline adapter for tests and local smoke without network."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from world_sim.llm.base import ChatMessage, LLMResponse, ToolCall


class FakeAdapter:
    """Maps simple imperative player lines to tool calls or grounded refusals."""

    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        del tools
        content = ""
        for message in reversed(messages):
            if message.role == "user":
                content = message.content.strip()
                break

        if "## Active Mode: chat_mode" in system or any(
            "SANDBOX CONTEXT" in message.content for message in messages
        ):
            return LLMResponse(
                text=(
                    "Mrs. Hale: The manor keeps its rooms as they are recorded. "
                    "I can speak with you here, but I will not change the house's "
                    "facts from this conversation alone."
                ),
                tool_calls=[],
            )

        if "Create a reviewable system lore draft" in content:
            prompt_match = re.search(r"Admin prompt:\s*(.+)", content)
            prompt_text = prompt_match.group(1).strip() if prompt_match else content
            return LLMResponse(
                text=(
                    f"Draft system lore grounded in the Quiet Manor canon: {prompt_text}. "
                    "The house keeps its recorded meaning carefully, and this draft "
                    "awaits explicit admin approval before it becomes canonical."
                ),
                tool_calls=[],
            )

        lower = content.lower()

        move = re.match(
            r"^(?:go|walk|move)\s+(north|south|east|west)$",
            lower,
        ) or re.fullmatch(r"(north|south|east|west)", lower)
        if move:
            return LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id=str(uuid4()),
                        name="move_player",
                        arguments={"direction": move.group(1)},
                    )
                ],
            )

        take = re.match(r"^(?:take|get|pick up)\s+(.+)$", lower)
        if take:
            return LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id=str(uuid4()),
                        name="take_item",
                        arguments={"item_name": take.group(1).strip()},
                    )
                ],
            )

        if lower in {"look", "look around", "l"}:
            return LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(id=str(uuid4()), name="look_room", arguments={})
                ],
            )

        examine = re.match(r"^(?:examine|inspect|x)\s+(.+)$", lower)
        if examine:
            target = examine.group(1).strip()
            if any(
                token in target
                for token in ("hale", "mrs", "npc", "woman", "caretaker")
            ):
                return LLMResponse(
                    text="",
                    tool_calls=[
                        ToolCall(
                            id=str(uuid4()),
                            name="examine_npc",
                            arguments={"npc_name": target},
                        )
                    ],
                )
            return LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id=str(uuid4()),
                        name="examine_item",
                        arguments={"item_name": target},
                    )
                ],
            )

        wait = re.match(r"^(?:wait|rest)(?:\s+(\d+)\s*(?:min|minutes)?)?$", lower)
        if wait:
            minutes = int(wait.group(1) or "5")
            return LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id=str(uuid4()),
                        name="advance_time",
                        arguments={"minutes": minutes},
                    )
                ],
            )

        # Unsupported hard-fact style claims: refuse in-character without tools.
        if any(
            phrase in lower
            for phrase in (
                "there is a dragon",
                "i open a portal",
                "secret elevator",
                "hidden spaceship",
            )
        ):
            return LLMResponse(
                text=(
                    "You search the quiet manor for any sign of that, but nothing "
                    "in the room answers the claim. The house remains as it is.\n"
                    "DM: That fact is not in current world state."
                ),
                tool_calls=[],
            )

        return LLMResponse(
            text=(
                "You pause and take in what is actually here. Nothing shifts unless "
                "you move, look, wait, or take something present."
            ),
            tool_calls=[],
        )
