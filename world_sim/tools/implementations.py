"""Play-mode tool implementations against SQLite runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from world_sim.authority import MutationConflict, WorldAuthority
from world_sim.builder.realize import RealizeError, realize_adjacent
from world_sim.config import MemorySettings, WorldExpansionSettings
from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.orchestrator.presentation import (
    present_item,
    present_npc,
    present_room,
)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


_DIRECTION_ALIASES = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "u": "up",
    "d": "down",
    "north": "north",
    "south": "south",
    "east": "east",
    "west": "west",
    "up": "up",
    "down": "down",
}


def normalize_direction(direction: str) -> str | None:
    """Map common direction aliases to canonical exit keys."""
    key = direction.strip().lower()
    return _DIRECTION_ALIASES.get(key)


class PlayTools:
    """Validated mutation/presentation tools for play_mode.

    Contested-capable mutations go through :class:`WorldAuthority` only.
    """

    def __init__(
        self,
        world: WorldAuthority | WorldStore,
        lore: ChromaManager,
        *,
        player_character_id: int,
        expansion: WorldExpansionSettings | None = None,
        memory: MemorySettings | None = None,
    ) -> None:
        memory_settings = memory or MemorySettings()
        if isinstance(world, WorldAuthority):
            self.world = world
            self.memory = world.memory_settings
        else:
            self.world = WorldAuthority(world, memory=memory_settings)
            self.memory = memory_settings
        self.lore = lore
        self.player_character_id = player_character_id
        self.expansion = expansion or WorldExpansionSettings()
        self.realized_this_session = 0
        self._handlers: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
            "move_player": self.move_player,
            "take_item": self.take_item,
            "look_room": self.look_room,
            "examine_item": self.examine_item,
            "examine_npc": self.examine_npc,
            "advance_time": self.advance_time,
            "record_memory": self.record_memory,
            "forget_memory": self.forget_memory,
        }

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(ok=False, message=f"Unknown tool '{name}'.")
        try:
            return handler(arguments)
        except MutationConflict as exc:
            # Contested refusal — runtime decided; LLM must narrate this result only.
            return ToolResult(
                ok=False,
                message=exc.message,
                data={"refusal": exc.to_dict()},
            )
        except ValueError as exc:
            # In-character refusal style; no raw DB error copy.
            return ToolResult(ok=False, message=str(exc))

    def _present(self, room_id: str, *, force_full: bool = False) -> str:
        return present_room(
            self.world.store,
            self.lore,
            player_character_id=self.player_character_id,
            room_id=room_id,
            force_full=force_full,
            show_pending_stubs=self.expansion.dynamic_expansion,
        )

    def move_player(self, arguments: dict[str, Any]) -> ToolResult:
        direction = str(arguments.get("direction", "")).strip()
        if not direction:
            return ToolResult(ok=False, message="You need a direction to move.")
        direction_norm = normalize_direction(direction)
        if direction_norm is None:
            return ToolResult(
                ok=False,
                message="That is not a direction the manor understands.",
            )
        current = self.world.get_player_room_id(self.player_character_id)
        if current is None:
            return ToolResult(ok=False, message="You are not placed in the world.")

        exits = self.world.list_exits(current)
        if direction_norm in exits:
            room = self.world.move_player(self.player_character_id, direction_norm)
            text = self._present(room.room_id)
            return ToolResult(
                ok=True,
                message=f"You go {direction_norm}.\n\n{text}",
                data={"room_id": room.room_id},
            )

        stub = self.world.get_pending_stub(current, direction_norm)
        if stub is None:
            return ToolResult(
                ok=False,
                message=(
                    "You try that way, but no such passage opens from here. "
                    "The manor keeps its present doors and no others."
                ),
            )

        if not self.expansion.dynamic_expansion:
            return ToolResult(
                ok=False,
                message=(
                    "That way is sealed for now. A frontier edge waits here, but "
                    "dynamic expansion is off — the campaign stays fixed."
                ),
            )

        try:
            realize_adjacent(
                self.world,
                self.lore,
                stub,
                settings=self.expansion,
                realized_this_session=self.realized_this_session,
                actor_player_character_id=self.player_character_id,
            )
        except RealizeError as exc:
            return ToolResult(
                ok=False,
                message=(
                    f"You press toward that way, but the house will not open it. "
                    f"({exc})"
                ),
            )
        except MutationConflict as exc:
            return ToolResult(
                ok=False,
                message=exc.message,
                data={"refusal": exc.to_dict()},
            )

        self.realized_this_session += 1
        room = self.world.move_player(self.player_character_id, direction_norm)
        text = self._present(room.room_id, force_full=True)
        return ToolResult(
            ok=True,
            message=(
                f"The way {direction_norm} settles into a lasting passage.\n"
                f"You go {direction_norm}.\n\n{text}"
            ),
            data={"room_id": room.room_id, "realized_stub": stub.stub_id},
        )

    def take_item(self, arguments: dict[str, Any]) -> ToolResult:
        room_id = self.world.get_player_room_id(self.player_character_id)
        if room_id is None:
            return ToolResult(ok=False, message="You are nowhere solid enough to take things.")

        item_instance_id = arguments.get("item_instance_id")
        if item_instance_id is not None:
            item_id = int(item_instance_id)
        else:
            name = str(arguments.get("item_name", "")).strip()
            if not name:
                return ToolResult(ok=False, message="Take what?")
            found = self.world.find_room_item_by_name(room_id, name)
            if found is None:
                return ToolResult(
                    ok=False,
                    message=(
                        "You look for that here, but it is not among the things "
                        "present in this room."
                    ),
                )
            item_id = found.id

        try:
            item = self.world.take_item_from_room(self.player_character_id, item_id)
        except MutationConflict as exc:
            return ToolResult(
                ok=False,
                message=exc.message,
                data={"refusal": exc.to_dict()},
            )
        except ValueError:
            return ToolResult(
                ok=False,
                message="You reach for it, but it is not here to take.",
            )
        label = item.name or f"item #{item.id}"
        return ToolResult(
            ok=True,
            message=f"You take the {label}.",
            data={"item_instance_id": item.id},
        )

    def look_room(self, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        room_id = self.world.get_player_room_id(self.player_character_id)
        if room_id is None:
            return ToolResult(ok=False, message="There is no room to look at.")
        text = self._present(room_id, force_full=True)
        return ToolResult(ok=True, message=text, data={"room_id": room_id})

    def examine_item(self, arguments: dict[str, Any]) -> ToolResult:
        item_instance_id = arguments.get("item_instance_id")
        if item_instance_id is not None:
            item = self.world.get_item_instance(int(item_instance_id))
        else:
            name = str(arguments.get("item_name", "")).strip()
            if not name:
                return ToolResult(ok=False, message="Examine what?")
            item = self.world.find_visible_item_by_name(
                self.player_character_id,
                name,
            )
        if item is None:
            return ToolResult(
                ok=False,
                message="You find nothing like that to examine here.",
            )
        text = present_item(
            self.world.store,
            self.lore,
            player_character_id=self.player_character_id,
            item_instance_id=item.id,
            force_full=True,
        )
        return ToolResult(
            ok=True,
            message=text,
            data={"item_instance_id": item.id},
        )

    def examine_npc(self, arguments: dict[str, Any]) -> ToolResult:
        room_id = self.world.get_player_room_id(self.player_character_id)
        if room_id is None:
            return ToolResult(ok=False, message="There is no room to examine NPCs in.")

        npc_id = arguments.get("npc_id")
        if npc_id:
            npc = self.world.get_npc(str(npc_id))
        else:
            name = str(arguments.get("npc_name", "")).strip()
            if not name:
                return ToolResult(ok=False, message="Examine whom?")
            npc = self.world.find_npc_by_name(name)

        if npc is None or npc.current_room_id != room_id:
            return ToolResult(
                ok=False,
                message="No such person is present here.",
            )
        text = present_npc(
            self.world.store,
            self.lore,
            player_character_id=self.player_character_id,
            npc_id=npc.npc_id,
            force_full=True,
        )
        return ToolResult(
            ok=True,
            message=text,
            data={"npc_id": npc.npc_id},
        )

    def advance_time(self, arguments: dict[str, Any]) -> ToolResult:
        minutes = int(arguments.get("minutes", 0))
        total = self.world.advance_time(minutes)
        return ToolResult(
            ok=True,
            message=f"Time passes ({minutes} minutes). World clock: {total} minutes elapsed.",
            data={"minutes_elapsed": total},
        )

    def record_memory(self, arguments: dict[str, Any]) -> ToolResult:
        if not self.memory.enabled:
            return ToolResult(
                ok=False,
                message="You try to fix that detail in mind, but lasting memory is sealed here.",
            )
        summary = str(arguments.get("summary", "")).strip()
        about_kind = arguments.get("about_kind")
        about_id = arguments.get("about_id")
        lore_key = arguments.get("lore_key")
        try:
            record = self.world.remember(
                actor_player_character_id=self.player_character_id,
                summary=summary,
                about_kind=str(about_kind) if about_kind else None,
                about_id=str(about_id) if about_id else None,
                lore_key=str(lore_key) if lore_key else None,
            )
        except ValueError as exc:
            return ToolResult(ok=False, message=str(exc))
        return ToolResult(
            ok=True,
            message=f"You fix that in mind (memory #{record.id}).",
            data={"memory_id": record.id},
        )

    def forget_memory(self, arguments: dict[str, Any]) -> ToolResult:
        if not self.memory.enabled:
            return ToolResult(
                ok=False,
                message="There is no lasting memory store open to clear.",
            )
        try:
            memory_id = int(arguments.get("memory_id"))
        except (TypeError, ValueError):
            return ToolResult(ok=False, message="Forget which memory id?")
        try:
            deleted = self.world.forget_memory(
                memory_id,
                actor_player_character_id=self.player_character_id,
            )
        except ValueError as exc:
            return ToolResult(ok=False, message=str(exc))
        if not deleted:
            return ToolResult(ok=False, message="That memory is already gone.")
        return ToolResult(
            ok=True,
            message=f"You let memory #{memory_id} fade.",
            data={"memory_id": memory_id},
        )
