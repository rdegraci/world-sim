"""World authority port and runtime event substrate (Phase 3a+4a)."""

from world_sim.authority.arbitration import MutationConflict, MutationGate
from world_sim.authority.bus import RuntimeEventBus
from world_sim.authority.events import (
    CHARACTER_ENTERED_ROOM,
    CHARACTER_LEFT_ROOM,
    CHARACTER_SAID,
    ITEM_TAKEN,
    NPC_CHAT_BUSY,
    NPC_CHAT_FREE,
    NPC_MOVED,
    PRESENCE_CHANGED,
    ROOM_REALIZED,
    SCENE_PUBLIC_EVENT_TYPES,
    TIME_ADVANCED,
    RuntimeEvent,
)
from world_sim.authority.port import WorldAuthority

__all__ = [
    "CHARACTER_ENTERED_ROOM",
    "CHARACTER_LEFT_ROOM",
    "CHARACTER_SAID",
    "ITEM_TAKEN",
    "MutationConflict",
    "MutationGate",
    "NPC_CHAT_BUSY",
    "NPC_CHAT_FREE",
    "NPC_MOVED",
    "PRESENCE_CHANGED",
    "ROOM_REALIZED",
    "SCENE_PUBLIC_EVENT_TYPES",
    "TIME_ADVANCED",
    "RuntimeEvent",
    "RuntimeEventBus",
    "WorldAuthority",
]
