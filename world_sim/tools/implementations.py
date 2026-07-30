"""Play-mode tool implementations against SQLite runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_ROOM,
    ChromaManager,
)
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


class PlayTools:
    """Validated mutation/presentation tools for play_mode."""

    def __init__(
        self,
        world: WorldStore,
        lore: ChromaManager,
        *,
        player_character_id: int,
    ) -> None:
        self.world = world
        self.lore = lore
        self.player_character_id = player_character_id
        self._handlers: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
            "move_player": self.move_player,
            "take_item": self.take_item,
            "look_room": self.look_room,
            "examine_item": self.examine_item,
            "examine_npc": self.examine_npc,
            "advance_time": self.advance_time,
        }

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(ok=False, message=f"Unknown tool '{name}'.")
        try:
            return handler(arguments)
        except ValueError as exc:
            # In-character refusal style; no raw DB error copy.
            return ToolResult(ok=False, message=str(exc))

    def move_player(self, arguments: dict[str, Any]) -> ToolResult:
        direction = str(arguments.get("direction", "")).strip()
        if not direction:
            return ToolResult(ok=False, message="You need a direction to move.")
        try:
            room = self.world.move_player(self.player_character_id, direction)
        except ValueError:
            return ToolResult(
                ok=False,
                message=(
                    "You try that way, but no such passage opens from here. "
                    "The manor keeps its present doors and no others."
                ),
            )
        text = present_room(
            self.world,
            self.lore,
            player_character_id=self.player_character_id,
            room_id=room.room_id,
            force_full=False,
        )
        return ToolResult(
            ok=True,
            message=f"You go {direction.lower()}.\n\n{text}",
            data={"room_id": room.room_id},
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
        text = present_room(
            self.world,
            self.lore,
            player_character_id=self.player_character_id,
            room_id=room_id,
            force_full=True,
        )
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
            self.world,
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
            self.world,
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
