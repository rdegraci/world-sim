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
