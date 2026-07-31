"""LLM-callable tool schemas for Slice 3 play."""

from __future__ import annotations

from typing import Any

PLAY_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "move_player",
            "description": "Move the player through an exit in the given direction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "Exit direction such as north, south, east, or west.",
                    }
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_item",
            "description": "Pick up an item instance that is in the player's current room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Visible name fragment of the item to take.",
                    },
                    "item_instance_id": {
                        "type": "integer",
                        "description": "Optional explicit item instance id.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look_room",
            "description": "Present the full canonical room description for the current room.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "examine_item",
            "description": "Present the full canonical description for a visible item instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string"},
                    "item_instance_id": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "examine_npc",
            "description": "Present the full canonical description for an NPC in the current room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "npc_name": {"type": "string"},
                    "npc_id": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "advance_time",
            "description": "Advance the shared world clock by a number of minutes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "minimum": 0},
                },
                "required": ["minutes"],
            },
        },
    },
]

MEMORY_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "record_memory",
            "description": (
                "Record a short bounded runtime memory for this player character. "
                "Does not rewrite canon lore. Optional lore_key links only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Short factual memory summary.",
                    },
                    "about_kind": {
                        "type": "string",
                        "description": "Optional: player_character, npc, room, item, world.",
                    },
                    "about_id": {
                        "type": "string",
                        "description": "Optional id matching about_kind.",
                    },
                    "lore_key": {
                        "type": "string",
                        "description": "Optional lore-key link (does not edit Chroma).",
                    },
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_memory",
            "description": "Forget one of this character's bounded memories by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "integer"},
                },
                "required": ["memory_id"],
            },
        },
    },
]


def play_tool_schemas(*, memory_enabled: bool = False) -> list[dict[str, Any]]:
    """Play-mode tool schemas; memory tools only when config enables them."""
    if not memory_enabled:
        return list(PLAY_TOOLS)
    return list(PLAY_TOOLS) + list(MEMORY_TOOLS)


PLAYER_CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "end_player_chat",
            "description": (
                "End the focused one-on-one Player Chat loop and return the player "
                "to normal play_mode. Use when the conversation is over or the player "
                "clearly wants to stop talking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Optional short reason the conversation ends.",
                    }
                },
                "required": [],
            },
        },
    },
]
