"""Runtime event types and payloads for scene-public world facts.

These events are the multiplayer / map substrate (Phase 3b consumers).
They are not full transcripts and must not leak hidden inventory or private chat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Scene-public / map-relevant event type constants
CHARACTER_LEFT_ROOM = "character_left_room"
CHARACTER_ENTERED_ROOM = "character_entered_room"
ITEM_TAKEN = "item_taken"
NPC_MOVED = "npc_moved"
ROOM_REALIZED = "room_realized"
TIME_ADVANCED = "time_advanced"
CHARACTER_SAID = "character_said"
PRESENCE_CHANGED = "presence_changed"
NPC_CHAT_BUSY = "npc_chat_busy"
NPC_CHAT_FREE = "npc_chat_free"

SCENE_PUBLIC_EVENT_TYPES = frozenset(
    {
        CHARACTER_LEFT_ROOM,
        CHARACTER_ENTERED_ROOM,
        ITEM_TAKEN,
        NPC_MOVED,
        ROOM_REALIZED,
        TIME_ADVANCED,
        CHARACTER_SAID,
        PRESENCE_CHANGED,
        NPC_CHAT_BUSY,
        NPC_CHAT_FREE,
    }
)


@dataclass(frozen=True)
class RuntimeEvent:
    """Structured runtime event suitable for persistence and later fan-out."""

    event_type: str
    payload: dict[str, Any]
    id: int | None = None
    created_at: str | None = None
    # Rooms that should receive this event under later interest management.
    room_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "room_ids": list(self.room_ids),
        }
