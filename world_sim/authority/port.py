"""WorldAuthority — sole port for contested-capable world mutations and tool reads."""

from __future__ import annotations

from typing import Any

from world_sim.authority.bus import RuntimeEventBus
from world_sim.authority.events import (
    CHARACTER_ENTERED_ROOM,
    CHARACTER_LEFT_ROOM,
    CHARACTER_SAID,
    ITEM_TAKEN,
    NPC_MOVED,
    ROOM_REALIZED,
    TIME_ADVANCED,
    RuntimeEvent,
)
from world_sim.db.world_store import (
    ItemInstanceRecord,
    Room,
    WorldStore,
)


class WorldAuthority:
    """Explicit authority seam over structured world state.

    Play tools and orchestrator mutation paths must use this port rather than
    ad-hoc SQLite writes. SQLite is the first backend via :class:`WorldStore`.
    A later store swap can replace ``store`` without rewriting tools.

    Phase 4a will add serial mutation / claim locks on top of this port.
    """

    def __init__(
        self,
        store: WorldStore,
        *,
        bus: RuntimeEventBus | None = None,
    ) -> None:
        self._store = store
        self._bus = bus or RuntimeEventBus(store)

    @property
    def store(self) -> WorldStore:
        """SQLite-backed store. Prefer authority methods for contested mutations."""
        return self._store

    @property
    def events(self) -> RuntimeEventBus:
        return self._bus

    @property
    def connection(self):  # noqa: ANN201 — mirrors WorldStore for rare callers
        return self._store.connection

    def emit_runtime_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        room_ids: tuple[str, ...] = (),
    ) -> RuntimeEvent:
        """Publish a scene-public runtime event (persisted + local subscribers)."""
        return self._bus.emit(event_type, payload, room_ids=room_ids)

    def append_runtime_event(self, event_type: str, payload: dict[str, Any]) -> int:
        """Compatibility wrapper used by frontier realize and older call sites."""
        room_ids: list[str] = []
        for key in ("room_id", "from_room_id", "to_room_id"):
            value = payload.get(key)
            if isinstance(value, str) and value not in room_ids:
                room_ids.append(value)
        event = self.emit_runtime_event(
            event_type,
            payload,
            room_ids=tuple(room_ids),
        )
        assert event.id is not None
        return event.id

    def list_runtime_events(
        self,
        *,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[tuple[int, str, str, str]]:
        return self._store.list_runtime_events(event_type=event_type, limit=limit)

    # --- Contested-capable mutations (emit scene-public events) ---

    def move_player(self, player_character_id: int, direction: str) -> Room:
        from_room = self._store.get_player_room_id(player_character_id)
        if from_room is None:
            raise ValueError("Player has no current room.")
        direction_norm = direction.strip().lower()
        room = self._store.move_player(player_character_id, direction_norm)
        self.emit_runtime_event(
            CHARACTER_LEFT_ROOM,
            {
                "player_character_id": player_character_id,
                "room_id": from_room,
                "to_room_id": room.room_id,
                "direction": direction_norm,
            },
            room_ids=(from_room,),
        )
        self.emit_runtime_event(
            CHARACTER_ENTERED_ROOM,
            {
                "player_character_id": player_character_id,
                "room_id": room.room_id,
                "from_room_id": from_room,
                "direction": direction_norm,
            },
            room_ids=(room.room_id,),
        )
        return room

    def take_item_from_room(
        self,
        player_character_id: int,
        item_instance_id: int,
    ) -> ItemInstanceRecord:
        room_id = self._store.get_player_room_id(player_character_id)
        item = self._store.take_item_from_room(player_character_id, item_instance_id)
        if room_id is not None:
            self.emit_runtime_event(
                ITEM_TAKEN,
                {
                    "player_character_id": player_character_id,
                    "item_instance_id": item.id,
                    "room_id": room_id,
                    "item_definition_id": item.item_definition_id,
                    "name": item.name,
                },
                room_ids=(room_id,),
            )
        return item

    def advance_time(self, minutes: int) -> int:
        total = self._store.advance_time(minutes)
        self.emit_runtime_event(
            TIME_ADVANCED,
            {
                "minutes": minutes,
                "minutes_elapsed": total,
            },
        )
        return total

    def set_npc_room(self, npc_id: str, room_id: str | None) -> None:
        npc = self._store.get_npc(npc_id)
        from_room = npc.current_room_id if npc else None
        self._store.set_npc_room(npc_id, room_id)
        if from_room == room_id:
            return
        room_ids = tuple(r for r in (from_room, room_id) if r)
        self.emit_runtime_event(
            NPC_MOVED,
            {
                "npc_id": npc_id,
                "from_room_id": from_room,
                "to_room_id": room_id,
            },
            room_ids=room_ids,
        )

    def record_room_realized(
        self,
        *,
        stub_id: str,
        room_id: str,
        lore_key: str,
        from_room_id: str | None = None,
        direction: str | None = None,
        already_existed: bool = False,
    ) -> RuntimeEvent:
        payload: dict[str, Any] = {
            "stub_id": stub_id,
            "room_id": room_id,
            "lore_key": lore_key,
            "already_existed": already_existed,
        }
        if from_room_id is not None:
            payload["from_room_id"] = from_room_id
        if direction is not None:
            payload["direction"] = direction
        room_ids = tuple(
            r for r in (room_id, from_room_id) if isinstance(r, str)
        )
        return self.emit_runtime_event(
            ROOM_REALIZED,
            payload,
            room_ids=room_ids,
        )

    def say_public(
        self,
        *,
        player_character_id: int,
        display_name: str,
        room_id: str,
        text: str,
    ) -> RuntimeEvent:
        """Emit scene-public speech in a room (not a private transcript share)."""
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            raise ValueError("Say what?")
        if len(cleaned) > 500:
            cleaned = cleaned[:497] + "…"
        return self.emit_runtime_event(
            CHARACTER_SAID,
            {
                "player_character_id": player_character_id,
                "display_name": display_name,
                "room_id": room_id,
                "text": cleaned,
            },
            room_ids=(room_id,),
        )

    # --- Authoritative reads used by tools / presentation (delegate) ---

    def __getattr__(self, name: str) -> Any:
        """Delegate non-overridden WorldStore API (reads, builder helpers, presentation)."""
        return getattr(self._store, name)
