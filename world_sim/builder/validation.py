"""World integrity and seed-plan validation."""

from __future__ import annotations

from dataclasses import dataclass, field

from world_sim.builder.linking import hierarchy_conflict, lore_exists
from world_sim.builder.plans import SeedPlan
from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_NPC,
    COLLECTION_ROOM,
    ChromaManager,
)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = [f"validate_world: {'OK' if self.ok else 'FAILED'}"]
        if self.errors:
            lines.append("Errors:")
            for error in self.errors:
                lines.append(f"  - {error}")
        if self.warnings:
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
        if self.ok and not self.warnings:
            lines.append("No issues found.")
        return "\n".join(lines)


def validate_world(
    world: WorldStore,
    lore: ChromaManager,
    *,
    plan: SeedPlan | None = None,
) -> ValidationResult:
    """Validate live SQLite/Chroma consistency, optionally overlaying a draft plan."""
    errors: list[str] = []
    warnings: list[str] = []

    _validate_live_world(world, lore, errors, warnings)
    if plan is not None:
        _validate_plan(plan, world, lore, errors, warnings)

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def _validate_live_world(
    world: WorldStore,
    lore: ChromaManager,
    errors: list[str],
    warnings: list[str],
) -> None:
    rooms = {room.room_id: room for room in world.list_rooms()}
    for room in rooms.values():
        if not lore_exists(lore, room.lore_key):
            errors.append(f"Missing lore key for room '{room.room_id}': {room.lore_key}")
        conflict = hierarchy_conflict("room", room.lore_key)
        if conflict:
            errors.append(conflict)

    for from_id, direction, to_id in world.list_all_exits():
        if from_id not in rooms:
            errors.append(f"Broken exit: unknown from_room '{from_id}' ({direction})")
        if to_id not in rooms:
            errors.append(
                f"Broken exit: '{from_id}' --{direction}--> unknown room '{to_id}'"
            )

    for definition in world.list_item_definitions():
        if not lore_exists(lore, definition.lore_key):
            errors.append(
                f"Missing lore key for item definition '{definition.item_id}': "
                f"{definition.lore_key}"
            )
        conflict = hierarchy_conflict("item_definition", definition.lore_key)
        if conflict:
            errors.append(conflict)

    definitions = {item.item_id for item in world.list_item_definitions()}
    for instance in world.list_all_item_instances():
        if instance.item_definition_id and instance.item_definition_id not in definitions:
            errors.append(
                f"Item instance {instance.id} references missing definition "
                f"'{instance.item_definition_id}'"
            )
        if instance.location_kind == "room":
            if not instance.location_id or instance.location_id not in rooms:
                errors.append(
                    f"Invalid item placement: instance {instance.id} in room "
                    f"'{instance.location_id}'"
                )

    for npc in world.list_npcs():
        if not npc.npc_lore:
            warnings.append(f"NPC '{npc.npc_id}' has empty npc_lore.")
        for key in npc.npc_lore:
            if not lore_exists(lore, key):
                errors.append(f"Missing NPC lore key for '{npc.npc_id}': {key}")
            conflict = hierarchy_conflict("npc", key)
            if conflict:
                errors.append(conflict)
        if npc.current_room_id and npc.current_room_id not in rooms:
            errors.append(
                f"Invalid NPC placement: '{npc.npc_id}' in unknown room "
                f"'{npc.current_room_id}'"
            )

    for entity_kind, entity_id, lore_key in world.list_all_lore_key_refs():
        if not lore_exists(lore, lore_key):
            errors.append(
                f"Broken lore-key ref: {entity_kind}:{entity_id} -> {lore_key}"
            )
        conflict = hierarchy_conflict(entity_kind, lore_key)
        if conflict:
            errors.append(conflict)

    _check_orphans(world, lore, warnings)


def _check_orphans(
    world: WorldStore,
    lore: ChromaManager,
    warnings: list[str],
) -> None:
    rooms = {room.room_id for room in world.list_rooms()}
    if not rooms:
        return

    linked: set[str] = set()
    for from_id, _direction, to_id in world.list_all_exits():
        linked.add(from_id)
        linked.add(to_id)
    for room_id in rooms:
        if room_id not in linked and len(rooms) > 1:
            warnings.append(f"Orphan room (no exits): '{room_id}'")

    used_room_keys = {room.lore_key for room in world.list_rooms()}
    for key in lore.list_keys(COLLECTION_ROOM):
        if key not in used_room_keys:
            warnings.append(f"Unused room lore (no SQLite room): {key}")

    used_item_keys = {item.lore_key for item in world.list_item_definitions()}
    for key in lore.list_keys(COLLECTION_ITEM):
        if key not in used_item_keys:
            warnings.append(f"Unused item lore (no definition): {key}")

    used_npc_keys: set[str] = set()
    for npc in world.list_npcs():
        used_npc_keys.update(npc.npc_lore)
    for key in lore.list_keys(COLLECTION_NPC):
        if key not in used_npc_keys:
            warnings.append(f"Unused NPC lore (no NPC attachment): {key}")


def _validate_plan(
    plan: SeedPlan,
    world: WorldStore,
    lore: ChromaManager,
    errors: list[str],
    warnings: list[str],
) -> None:
    if plan.gaps:
        for gap in plan.gaps:
            errors.append(f"Brief/lore gap: {gap}")

    room_ids = {room.room_id for room in world.list_rooms()}
    room_ids.update(room["room_id"] for room in plan.rooms if room.get("room_id"))

    item_ids = {item.item_id for item in world.list_item_definitions()}
    item_ids.update(item["item_id"] for item in plan.items if item.get("item_id"))

    npc_ids = {npc.npc_id for npc in world.list_npcs()}
    npc_ids.update(npc["npc_id"] for npc in plan.npcs if npc.get("npc_id"))

    for room in plan.rooms:
        lore_key = str(room.get("lore_key") or "")
        if lore_key and not lore_exists(lore, lore_key):
            errors.append(
                f"Plan room '{room.get('room_id')}' missing lore key '{lore_key}'"
            )
        if lore_key:
            conflict = hierarchy_conflict("room", lore_key)
            if conflict:
                errors.append(conflict)

    for item in plan.items:
        lore_key = str(item.get("lore_key") or "")
        action = item.get("action")
        if action != "place_only" and lore_key and not lore_exists(lore, lore_key):
            errors.append(
                f"Plan item '{item.get('item_id')}' missing lore key '{lore_key}'"
            )
        if lore_key:
            conflict = hierarchy_conflict("item_definition", lore_key)
            if conflict:
                errors.append(conflict)
        place_in = item.get("place_in")
        if place_in and place_in not in room_ids:
            errors.append(
                f"Invalid item placement in plan: '{item.get('item_id')}' -> '{place_in}'"
            )

    for npc in plan.npcs:
        for key in npc.get("npc_lore") or []:
            if not lore_exists(lore, key):
                errors.append(f"Plan NPC '{npc.get('npc_id')}' missing lore key '{key}'")
            conflict = hierarchy_conflict("npc", key)
            if conflict:
                errors.append(conflict)
        room_id = npc.get("current_room_id")
        if room_id and room_id not in room_ids:
            errors.append(
                f"Invalid NPC placement in plan: '{npc.get('npc_id')}' -> '{room_id}'"
            )

    for exit_op in plan.exits:
        from_id = exit_op.get("from_room_id")
        to_id = exit_op.get("to_room_id")
        if from_id not in room_ids:
            errors.append(f"Plan exit from unknown room '{from_id}'")
        if to_id not in room_ids:
            errors.append(f"Plan exit to unknown room '{to_id}'")

    for attachment in plan.attachments:
        lore_key = str(attachment.get("lore_key") or "")
        if lore_key and not lore_exists(lore, lore_key):
            errors.append(
                f"Plan attachment missing lore: "
                f"{attachment.get('entity_kind')}:{attachment.get('entity_id')} "
                f"-> {lore_key}"
            )
        kind = str(attachment.get("entity_kind") or "")
        if lore_key:
            conflict = hierarchy_conflict(kind, lore_key)
            if conflict:
                errors.append(conflict)

    if plan.brief:
        _validate_brief_constraints(plan, errors)


def _validate_brief_constraints(
    plan: SeedPlan,
    errors: list[str],
) -> None:
    brief = plan.brief or {}
    constraints = brief.get("constraints") or {}
    max_rooms = constraints.get("max_rooms")
    max_items = constraints.get("max_items")
    max_npcs = constraints.get("max_npcs")

    new_rooms = [room for room in plan.rooms if room.get("action") == "create"]
    new_items = [item for item in plan.items if item.get("action") == "create"]
    new_npcs = [npc for npc in plan.npcs if npc.get("action") == "create"]

    if max_rooms is not None and len(new_rooms) > int(max_rooms):
        errors.append(
            f"Brief constraint violated: max_rooms={max_rooms}, "
            f"plan creates {len(new_rooms)}"
        )
    if max_items is not None and len(new_items) > int(max_items):
        errors.append(
            f"Brief constraint violated: max_items={max_items}, "
            f"plan creates {len(new_items)}"
        )
    if max_npcs is not None and len(new_npcs) > int(max_npcs):
        errors.append(
            f"Brief constraint violated: max_npcs={max_npcs}, "
            f"plan creates {len(new_npcs)}"
        )

    planned_exits = {
        (
            exit_op.get("from_room_id"),
            str(exit_op.get("direction") or "").lower(),
            exit_op.get("to_room_id"),
        )
        for exit_op in plan.exits
    }
    for link in brief.get("must_link") or []:
        triple = (link.get("from"), str(link.get("direction") or "").lower(), link.get("to"))
        if triple not in planned_exits:
            errors.append(
                f"Brief must_link missing from plan: "
                f"{triple[0]} --{triple[1]}--> {triple[2]}"
            )

    for placement in brief.get("must_place") or []:
        kind = placement.get("kind")
        entity_id = placement.get("id")
        room = placement.get("room")
        if kind == "item":
            matched = any(
                item.get("item_id") == entity_id and item.get("place_in") == room
                for item in plan.items
            )
            if not matched:
                errors.append(
                    f"Brief must_place missing: item '{entity_id}' in '{room}'"
                )
        elif kind == "npc":
            matched = any(
                npc.get("npc_id") == entity_id and npc.get("current_room_id") == room
                for npc in plan.npcs
            )
            if not matched:
                errors.append(
                    f"Brief must_place missing: npc '{entity_id}' in '{room}'"
                )

    haystacks: list[str] = []
    for room in plan.rooms:
        haystacks.extend([str(room.get("room_id") or ""), str(room.get("name") or "")])
    for item in plan.items:
        haystacks.extend([str(item.get("item_id") or ""), str(item.get("name") or "")])
    for npc in plan.npcs:
        haystacks.extend([str(npc.get("npc_id") or ""), str(npc.get("name") or "")])
    blob = " ".join(haystacks).lower()
    for banned in brief.get("do_not") or []:
        token = str(banned).strip().lower()
        if token and token in blob:
            errors.append(f"Brief do_not violated: plan mentions '{banned}'")
