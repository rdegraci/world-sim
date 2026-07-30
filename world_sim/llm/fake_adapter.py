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

        if "## Active Loop: Player Chat" in system or any(
            "PLAYER CHAT CONTEXT" in message.content for message in messages
        ):
            return self._player_chat_response(content)

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

        if "Create a reviewable room lore draft" in content:
            prompt_match = re.search(r"Admin prompt:\s*(.+)", content)
            prompt_text = prompt_match.group(1).strip() if prompt_match else content
            key_match = re.search(r"Target lore_key:\s*(\S+)", content)
            key = key_match.group(1) if key_match else "room:unknown"
            return LLMResponse(
                text=(
                    f"Revised room lore for {key}: {prompt_text}. "
                    "The manor room keeps this meaning only after admin approval."
                ),
                tool_calls=[],
            )

        if "Create a reviewable item lore draft" in content:
            prompt_match = re.search(r"Admin prompt:\s*(.+)", content)
            prompt_text = prompt_match.group(1).strip() if prompt_match else content
            key_match = re.search(r"Target lore_key:\s*(\S+)", content)
            key = key_match.group(1) if key_match else "item:unknown"
            return LLMResponse(
                text=(
                    f"Revised item lore for {key}: {prompt_text}. "
                    "The object meaning awaits explicit admin approval."
                ),
                tool_calls=[],
            )

        if "Create a reviewable NPC draft" in content:
            prompt_match = re.search(r"Admin prompt:\s*(.+)", content)
            prompt_text = prompt_match.group(1).strip() if prompt_match else "new npc"
            slug = re.sub(r"[^a-z0-9]+", "_", prompt_text.lower()).strip("_")[:24] or "npc"
            return LLMResponse(
                text=(
                    f"NPC_ID: {slug}\n"
                    f"NAME: {slug.replace('_', ' ').title()}\n"
                    f"DESCRIPTION:\n"
                    f"A Quiet Manor figure drafted from: {prompt_text}. "
                    "They remain consistent with recorded rooms and will not invent facts."
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

    def _player_chat_response(self, content: str) -> LLMResponse:
        lower = content.lower()
        if any(
            phrase in lower
            for phrase in (
                "give you the key",
                "take my brass key",
                "i hand you",
                "here, take this",
                "transfer the",
            )
        ):
            return LLMResponse(
                text=(
                    "Mrs. Hale: I hear what you mean, but I will not take or give "
                    "objects as settled fact from this talk alone. What we each "
                    "carry stays as the house records it."
                ),
                tool_calls=[],
            )
        if any(
            phrase in lower
            for phrase in (
                "there is a dragon",
                "secret elevator",
                "hidden spaceship",
                "i open a portal",
            )
        ):
            return LLMResponse(
                text=(
                    "Mrs. Hale: I see no such thing here, and I will not agree that "
                    "it is present. The manor keeps only what is recorded.\n"
                    "DM: That fact is not in current world state."
                ),
                tool_calls=[],
            )
        if any(
            phrase in lower
            for phrase in ("goodbye", "i should go", "end this", "stop talking")
        ):
            return LLMResponse(
                text="Mrs. Hale: Of course. We can speak again when you wish.",
                tool_calls=[
                    ToolCall(
                        id=str(uuid4()),
                        name="end_player_chat",
                        arguments={"reason": "farewell"},
                    )
                ],
            )
        return LLMResponse(
            text=(
                "Mrs. Hale: The Quiet Manor keeps its rooms carefully. "
                "Ask me about what is present, and I will answer as I can."
            ),
            tool_calls=[],
        )
