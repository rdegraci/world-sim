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
from world_sim.config import MemorySettings
from world_sim.db.world_store import (
    ItemInstanceRecord,
    MemoryRecord,
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
        memory: MemorySettings | None = None,
    ) -> None:
        self._store = store
        self._bus = bus or RuntimeEventBus(store)
        self._gate = gate or MutationGate()
        self._memory = memory or MemorySettings()

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
    def memory_settings(self) -> MemorySettings:
        return self._memory

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

    # --- Bounded memory (Phase 4b1; serial apply; no scene-public fan-out) ---

    def remember(
        self,
        *,
        actor_player_character_id: int,
        summary: str,
        subject_kind: str = "player_character",
        subject_id: str | None = None,
        about_kind: str | None = None,
        about_id: str | None = None,
        lore_key: str | None = None,
    ) -> MemoryRecord:
        """Record a bounded runtime memory for the acting character (or NPC about them).

        Does not write Chroma or rewrite canon. ``lore_key`` is an optional link only.
        Private — not emitted as a scene-public runtime event.
        """

        def _apply() -> MemoryRecord:
            if not self._memory.enabled:
                raise ValueError(
                    "Bounded memory is off. Set memory.enabled: true in config.yaml."
                )
            cleaned = " ".join(str(summary).split()).strip()
            if not cleaned:
                raise ValueError("Remember what?")
            if len(cleaned) > self._memory.max_summary_chars:
                raise ValueError(
                    f"Memory summary must be at most "
                    f"{self._memory.max_summary_chars} characters."
                )

            kind = subject_kind.strip().lower()
            if kind not in {"player_character", "npc"}:
                raise ValueError("subject_kind must be player_character or npc.")

            actor = str(actor_player_character_id)
            resolved_about_kind = about_kind
            resolved_about_id = about_id
            if kind == "player_character":
                resolved_subject = subject_id.strip() if subject_id else actor
                if resolved_subject != actor:
                    raise ValueError(
                        "You can only record memory for your own character."
                    )
            else:
                if not subject_id or not str(subject_id).strip():
                    raise ValueError("NPC memory requires subject_id (npc_id).")
                resolved_subject = str(subject_id).strip()
                npc = self._store.get_npc(resolved_subject)
                if npc is None:
                    raise ValueError("That person is not known to the manor.")
                # NPC memories written by a player must be about that player.
                resolved_about_kind = (about_kind or "player_character").strip().lower()
                resolved_about_id = (about_id or actor).strip()
                if (
                    resolved_about_kind != "player_character"
                    or resolved_about_id != actor
                ):
                    raise ValueError(
                        "You may only attach NPC memory that is about your character."
                    )

            if resolved_about_kind is not None:
                resolved_about_kind = resolved_about_kind.strip().lower() or None
            if resolved_about_id is not None:
                resolved_about_id = str(resolved_about_id).strip() or None
            if (resolved_about_kind is None) != (resolved_about_id is None):
                raise ValueError("about_kind and about_id must be set together.")
            if resolved_about_kind is not None and resolved_about_kind not in {
                "player_character",
                "npc",
                "room",
                "item",
                "world",
            }:
                raise ValueError("Invalid about_kind.")

            link = lore_key.strip() if lore_key else None
            if link == "":
                link = None

            expires_at: str | None = None
            if self._memory.ttl_days > 0:
                expires_at = self._store.connection.execute(
                    """
                    SELECT strftime(
                        '%Y-%m-%dT%H:%M:%fZ',
                        'now',
                        ?
                    ) AS expires_at
                    """,
                    (f"+{self._memory.ttl_days} days",),
                ).fetchone()["expires_at"]

            record = self._store.insert_memory(
                subject_kind=kind,
                subject_id=resolved_subject,
                summary=cleaned,
                about_kind=resolved_about_kind,
                about_id=resolved_about_id,
                lore_key=link,
                expires_at=expires_at,
            )
            self._store.trim_memories_for_subject(
                kind,
                resolved_subject,
                keep=self._memory.max_per_subject,
            )
            # Re-fetch in case trim removed this row (should not if newest).
            refreshed = self._store.get_memory(record.id)
            if refreshed is None:
                raise ValueError("Memory could not be retained under current caps.")
            return refreshed

        return self._gate.run_serial(_apply)

    def forget_memory(
        self,
        memory_id: int,
        *,
        actor_player_character_id: int,
    ) -> bool:
        """Delete a memory the actor is allowed to see/own. Serial; no event fan-out."""

        def _apply() -> bool:
            if not self._memory.enabled:
                raise ValueError(
                    "Bounded memory is off. Set memory.enabled: true in config.yaml."
                )
            record = self._store.get_memory(memory_id)
            if record is None:
                return False
            actor = str(actor_player_character_id)
            owned_pc = (
                record.subject_kind == "player_character"
                and record.subject_id == actor
            )
            owned_npc_about = (
                record.subject_kind == "npc"
                and record.about_kind == "player_character"
                and record.about_id == actor
            )
            if not (owned_pc or owned_npc_about):
                raise ValueError("That memory is not yours to forget.")
            return self._store.delete_memory(memory_id)

        return self._gate.run_serial(_apply)

    def list_visible_memories(
        self,
        viewer_player_character_id: int,
        *,
        npc_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Memories visible to one player — never another PC's private subject rows.

        Always includes the viewer's own PC memories. When ``npc_id`` is set (Player
        Chat), also includes that NPC's memories about the viewer.
        """
        if not self._memory.enabled:
            return []
        viewer = str(viewer_player_character_id)
        own = self._store.list_memories_for_subject(
            "player_character",
            viewer,
            limit=limit,
        )
        by_id = {m.id: m for m in own}
        if npc_id:
            for mem in self._store.list_npc_memories_about_player(
                npc_id,
                viewer_player_character_id,
                limit=limit,
            ):
                by_id[mem.id] = mem
        ordered = sorted(
            by_id.values(),
            key=lambda m: (m.created_at, m.id),
            reverse=True,
        )
        return ordered[:limit]

    def format_visible_memories(
        self,
        viewer_player_character_id: int,
        *,
        npc_id: str | None = None,
        limit: int = 12,
    ) -> str:
        """Compact text block for LLM context, or empty string when disabled/none."""
        memories = self.list_visible_memories(
            viewer_player_character_id,
            npc_id=npc_id,
            limit=limit,
        )
        if not memories:
            return ""
        lines = []
        for mem in memories:
            about = ""
            if mem.about_kind and mem.about_id:
                about = f" about {mem.about_kind}:{mem.about_id}"
            link = f" lore_key={mem.lore_key}" if mem.lore_key else ""
            lines.append(
                f"- #{mem.id} [{mem.subject_kind}:{mem.subject_id}]{about}{link}: "
                f"{mem.summary}"
            )
        return (
            "BOUNDED MEMORY (runtime only; not canon; do not invent extra memories)\n"
            + "\n".join(lines)
        )

    # --- Authoritative reads used by tools / presentation (delegate) ---

    def __getattr__(self, name: str) -> Any:
        """Delegate non-overridden WorldStore API (reads, builder helpers, presentation)."""
        return getattr(self._store, name)
