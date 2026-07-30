"""WorldAuthority — sole port for contested-capable world mutations and tool reads."""

from __future__ import annotations

from typing import Any

from world_sim.authority.arbitration import (
    MutationConflict,
    MutationGate,
    chat_resource,
    exit_resource,
    holder_for_player,
    item_resource,
)
from world_sim.authority.bus import RuntimeEventBus
from world_sim.authority.events import (
    CHARACTER_ENTERED_ROOM,
    CHARACTER_LEFT_ROOM,
    CHARACTER_SAID,
    ITEM_TAKEN,
    NPC_CHAT_BUSY,
    NPC_CHAT_FREE,
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

    Phase 4a: serial mutation queue + short claim locks for contested resources.
    """

    def __init__(
        self,
        store: WorldStore,
        *,
        bus: RuntimeEventBus | None = None,
        gate: MutationGate | None = None,
    ) -> None:
        self._store = store
        self._bus = bus or RuntimeEventBus(store)
        self._gate = gate or MutationGate()

    @property
    def store(self) -> WorldStore:
        """SQLite-backed store. Prefer authority methods for contested mutations."""
        return self._store

    @property
    def events(self) -> RuntimeEventBus:
        return self._bus

    @property
    def gate(self) -> MutationGate:
        return self._gate

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

    # --- Contested-capable mutations (serial + claims + scene-public events) ---

    def move_player(self, player_character_id: int, direction: str) -> Room:
        def _apply() -> Room:
            from_room = self._store.get_player_room_id(player_character_id)
            if from_room is None:
                raise ValueError("Player has no current room.")
            direction_norm = direction.strip().lower()
            resource = exit_resource(from_room, direction_norm)
            holder = holder_for_player(player_character_id)
            if not self._gate.try_claim(resource, holder):
                raise MutationConflict(
                    "exit_claimed",
                    "That way is crowded for a moment — try again.",
                    resource=resource,
                )
            try:
                exits = self._store.list_exits(from_room)
                if direction_norm not in exits:
                    raise ValueError(f"No exit '{direction_norm}' from this room.")
                room = self._store.move_player(player_character_id, direction_norm)
            finally:
                self._gate.release_claim(resource, holder)

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

        return self._gate.run_serial(_apply)

    def take_item_from_room(
        self,
        player_character_id: int,
        item_instance_id: int,
    ) -> ItemInstanceRecord:
        def _apply() -> ItemInstanceRecord:
            resource = item_resource(item_instance_id)
            holder = holder_for_player(player_character_id)
            if not self._gate.try_claim(resource, holder):
                raise MutationConflict(
                    "item_claimed",
                    "Someone else reaches for that at the same time — and gets there first.",
                    resource=resource,
                )
            try:
                room_id = self._store.get_player_room_id(player_character_id)
                item = self._store.get_item_instance(item_instance_id)
                if (
                    item is None
                    or room_id is None
                    or item.location_kind != "room"
                    or item.location_id != room_id
                ):
                    raise MutationConflict(
                        "item_gone",
                        "You reach for it, but it is not here to take.",
                        resource=resource,
                    )
                taken = self._store.take_item_from_room(
                    player_character_id,
                    item_instance_id,
                )
            finally:
                self._gate.release_claim(resource, holder)

            if room_id is not None:
                self.emit_runtime_event(
                    ITEM_TAKEN,
                    {
                        "player_character_id": player_character_id,
                        "item_instance_id": taken.id,
                        "room_id": room_id,
                        "item_definition_id": taken.item_definition_id,
                        "name": taken.name,
                    },
                    room_ids=(room_id,),
                )
            return taken

        return self._gate.run_serial(_apply)

    def advance_time(self, minutes: int) -> int:
        def _apply() -> int:
            total = self._store.advance_time(minutes)
            self.emit_runtime_event(
                TIME_ADVANCED,
                {
                    "minutes": minutes,
                    "minutes_elapsed": total,
                },
            )
            return total

        return self._gate.run_serial(_apply)

    def set_npc_room(self, npc_id: str, room_id: str | None) -> None:
        def _apply() -> None:
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

        self._gate.run_serial(_apply)

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
        def _apply() -> RuntimeEvent:
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

        return self._gate.run_serial(_apply)

    def say_public(
        self,
        *,
        player_character_id: int,
        display_name: str,
        room_id: str,
        text: str,
    ) -> RuntimeEvent:
        """Emit scene-public speech in a room (not a private transcript share)."""

        def _apply() -> RuntimeEvent:
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

        return self._gate.run_serial(_apply)

    # --- Player Chat leases (exclusive per NPC) ---

    def acquire_player_chat_lease(
        self,
        npc_id: str,
        player_character_id: int,
        *,
        connection_id: str | None = None,
        ttl_sec: float = 3600.0,
    ) -> None:
        """Claim exclusive focused Player Chat on ``npc_id`` (serial + claim lock)."""

        def _apply() -> None:
            resource = chat_resource(npc_id)
            holder = holder_for_player(player_character_id)
            existing = self._gate.get_claim(resource)
            if existing is not None and existing.holder != holder:
                raise MutationConflict(
                    "chat_leased",
                    (
                        "That person is already in focused conversation with someone else. "
                        "You see they are engaged — but you cannot hear their private words."
                    ),
                    resource=resource,
                )
            ok = self._gate.try_claim(
                resource,
                holder,
                ttl_sec=ttl_sec,
                meta={
                    "npc_id": npc_id,
                    "player_character_id": player_character_id,
                    "connection_id": connection_id,
                },
            )
            if not ok:
                raise MutationConflict(
                    "chat_leased",
                    (
                        "That person is already in focused conversation with someone else. "
                        "You see they are engaged — but you cannot hear their private words."
                    ),
                    resource=resource,
                )
            npc = self._store.get_npc(npc_id)
            room_id = npc.current_room_id if npc else None
            if room_id:
                self.emit_runtime_event(
                    NPC_CHAT_BUSY,
                    {
                        "npc_id": npc_id,
                        "room_id": room_id,
                        "busy": True,
                    },
                    room_ids=(room_id,),
                )

        self._gate.run_serial(_apply)

    def release_player_chat_lease(
        self,
        npc_id: str,
        player_character_id: int,
    ) -> None:
        def _apply() -> None:
            resource = chat_resource(npc_id)
            holder = holder_for_player(player_character_id)
            existing = self._gate.get_claim(resource)
            if existing is None or existing.holder != holder:
                return
            self._gate.release_claim(resource, holder)
            npc = self._store.get_npc(npc_id)
            room_id = npc.current_room_id if npc else None
            if room_id:
                self.emit_runtime_event(
                    NPC_CHAT_FREE,
                    {
                        "npc_id": npc_id,
                        "room_id": room_id,
                        "busy": False,
                    },
                    room_ids=(room_id,),
                )

        self._gate.run_serial(_apply)

    def get_player_chat_lease(self, npc_id: str) -> dict[str, Any] | None:
        claim = self._gate.get_claim(chat_resource(npc_id))
        if claim is None:
            return None
        return {
            "npc_id": npc_id,
            "holder": claim.holder,
            "player_character_id": claim.meta.get("player_character_id"),
            "connection_id": claim.meta.get("connection_id"),
        }

    def list_busy_npcs_in_room(self, room_id: str) -> list[dict[str, Any]]:
        """NPCs in ``room_id`` that hold an active Player Chat lease (busy presence)."""
        busy: list[dict[str, Any]] = []
        for npc in self._store.list_npcs_in_room(room_id):
            lease = self.get_player_chat_lease(npc.npc_id)
            if lease is None:
                continue
            busy.append(
                {
                    "npc_id": npc.npc_id,
                    "name": npc.name,
                    "busy": True,
                }
            )
        return busy

    # --- Authoritative reads used by tools / presentation (delegate) ---

    def __getattr__(self, name: str) -> Any:
        """Delegate non-overridden WorldStore API (reads, builder helpers, presentation)."""
        return getattr(self._store, name)
