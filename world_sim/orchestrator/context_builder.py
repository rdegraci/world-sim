"""Build grounded LLM context from SQLite first, then linked Chroma lore."""

from __future__ import annotations

from dataclasses import dataclass

from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)
from world_sim.lore.seed import SYSTEM_LORE_KEY


@dataclass(frozen=True)
class PlayContext:
    player_character_id: int
    room_id: str | None
    system_lore: str | None
    room_presentation_hint: str | None
    inventory_summary: str
    world_minutes: int
    text: str


class ContextBuilder:
    """Resolve structured state, then attach canonical lore by explicit keys."""

    def __init__(self, world: WorldStore, lore: ChromaManager) -> None:
        self.world = world
        self.lore = lore

    def build(
        self,
        player_character_id: int,
        *,
        include_frontier_stubs: bool = False,
    ) -> PlayContext:
        system_lore = self.lore.get_lore(COLLECTION_SYSTEM, SYSTEM_LORE_KEY)
        room_id = self.world.get_player_room_id(player_character_id)
        room_presentation_hint = None
        room_block = "Room: (none)"
        if room_id is not None:
            room = self.world.get_room(room_id)
            room_presentation_hint = self._room_context_summary(
                player_character_id,
                room_id,
            )
            lore_text = (
                self.lore.get_lore(COLLECTION_ROOM, room.lore_key)
                if room is not None
                else None
            )
            exits = self.world.list_exits(room_id)
            exit_lines = [f"- {direction} -> {target}" for direction, target in sorted(exits.items())]
            if include_frontier_stubs:
                pending = self.world.list_pending_stub_directions(room_id)
                for direction, target in sorted(pending.items()):
                    if direction not in exits:
                        exit_lines.append(
                            f"- {direction} -> {target} "
                            "(pending frontier stub; call move_player to realize/cross)"
                        )
            items = self.world.list_items_in_room(room_id)
            item_lines = []
            for item in items:
                item_lore = (
                    self.lore.get_lore(COLLECTION_ITEM, item.definition_key)
                    if item.definition_key
                    else None
                )
                item_lines.append(
                    f"- #{item.id} {item.name}: lore_key={item.definition_key}; "
                    f"canon_present={bool(item_lore)}"
                )
            exits_block = "\n".join(exit_lines) if exit_lines else "- none"
            room_block = (
                f"Room id={room_id} name={room.name if room else '?'}\n"
                f"Room lore_key={room.lore_key if room else '?'}\n"
                f"Room lore text:\n{lore_text or '(missing)'}\n"
                f"Presentation hint: {room_presentation_hint}\n"
                f"Exits (authoritative; use move_player for these directions):\n"
                f"{exits_block}\n"
                f"Items in room:\n"
                + ("\n".join(item_lines) if item_lines else "- none")
            )

        inventory = self.world.list_player_items(player_character_id)
        if inventory:
            inv_lines = [
                f"- #{item.id} {item.name} ({item.definition_key})"
                for item in inventory
            ]
            inventory_summary = "\n".join(inv_lines)
        else:
            inventory_summary = "- empty"

        minutes = self.world.get_minutes_elapsed()
        frontier_note = ""
        if include_frontier_stubs:
            frontier_note = (
                " Pending frontier exits are valid move_player targets when listed; "
                "do not narrate them as solid walls."
            )
        text = (
            "AUTHORITATIVE RUNTIME CONTEXT (SQLite first, then linked lore)\n"
            f"Player character id: {player_character_id}\n"
            f"World minutes elapsed: {minutes}\n"
            f"System lore key={SYSTEM_LORE_KEY}\n"
            f"System lore:\n{system_lore or '(missing)'}\n\n"
            f"{room_block}\n\n"
            f"Inventory:\n{inventory_summary}\n\n"
            "Rules reminder: do not invent unsupported exits, items, or rooms. "
            "Use tools for movement, taking items, looking, examining, and time. "
            "False player assertions must be refused in-character."
            f"{frontier_note}"
        )
        return PlayContext(
            player_character_id=player_character_id,
            room_id=room_id,
            system_lore=system_lore,
            room_presentation_hint=room_presentation_hint,
            inventory_summary=inventory_summary,
            world_minutes=minutes,
            text=text,
        )

    def _room_context_summary(self, player_character_id: int, room_id: str) -> str:
        """Describe how the room would present without mutating seen-state."""
        room = self.world.get_room(room_id)
        if room is None:
            return ""
        full = self.lore.get_lore(COLLECTION_ROOM, room.lore_key) or room.name
        seen, recap = self.world.get_room_presentation(player_character_id, room_id)
        if seen and recap:
            return f"(revisit recap) {recap}"
        return f"(first/full candidate) {full}"
