"""Apply approved seed plans to SQLite (explicit admin approval only)."""

from __future__ import annotations

from world_sim.builder.plans import PLAN_STATUS_APPLIED, PLAN_STATUS_DRAFT, SeedPlan
from world_sim.builder.validation import ValidationResult, validate_world
from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import ChromaManager


class ApplyError(RuntimeError):
    """Raised when a seed plan cannot be applied."""


def apply_seed_plan(
    world: WorldStore,
    lore: ChromaManager,
    plan: SeedPlan,
    *,
    force: bool = False,
) -> SeedPlan:
    """Commit a draft plan to SQLite after validation.

    Never auto-called. Exp-007 unsupervised apply is explicitly out of scope.
    """
    if plan.status == PLAN_STATUS_APPLIED and not force:
        raise ApplyError(f"Plan '{plan.plan_id}' is already applied.")
    if plan.status != PLAN_STATUS_DRAFT and not force:
        raise ApplyError(
            f"Plan '{plan.plan_id}' status is '{plan.status}'; only drafts apply."
        )

    result: ValidationResult = validate_world(world, lore, plan=plan)
    if not result.ok:
        joined = "; ".join(result.errors)
        raise ApplyError(f"Refusing to apply invalid plan: {joined}")

    for room in plan.rooms:
        action = room.get("action")
        if action in {"create", "update", "attach_only"}:
            lore_key = str(room.get("lore_key") or "")
            if not lore_key:
                raise ApplyError(f"Room '{room.get('room_id')}' missing lore_key.")
            world.upsert_room(
                str(room["room_id"]),
                str(room.get("name") or room["room_id"]),
                lore_key,
            )

    for item in plan.items:
        action = item.get("action")
        item_id = str(item["item_id"])
        if action in {"create", "update", "attach_only"}:
            lore_key = str(item.get("lore_key") or "")
            if not lore_key:
                raise ApplyError(f"Item '{item_id}' missing lore_key.")
            world.upsert_item_definition(
                item_id,
                str(item.get("name") or item_id),
                lore_key,
            )
        place_in = item.get("place_in")
        if place_in:
            definition = world.get_item_definition(item_id)
            if definition is None:
                raise ApplyError(
                    f"Cannot place item '{item_id}': definition missing after apply."
                )
            already = any(
                instance.item_definition_id == item_id
                and instance.location_kind == "room"
                and instance.location_id == place_in
                for instance in world.list_items_in_room(str(place_in))
            )
            if not already:
                world.create_item_instance(
                    item_definition_id=item_id,
                    location_kind="room",
                    location_id=str(place_in),
                )

    for npc in plan.npcs:
        action = npc.get("action")
        npc_id = str(npc["npc_id"])
        if action == "place_only":
            if world.get_npc(npc_id) is None:
                raise ApplyError(f"Cannot place unknown NPC '{npc_id}'.")
            room_id = npc.get("current_room_id")
            world.set_npc_room(npc_id, str(room_id) if room_id else None)
            continue
        if action in {"create", "update", "attach_only"}:
            npc_lore = list(npc.get("npc_lore") or [])
            if not npc_lore:
                raise ApplyError(f"NPC '{npc_id}' requires npc_lore keys.")
            existing = world.get_npc(npc_id)
            world.upsert_npc(
                npc_id,
                str(npc.get("name") or npc_id),
                npc_lore=npc_lore,
                current_room_id=(
                    npc.get("current_room_id")
                    if npc.get("current_room_id") is not None
                    else (existing.current_room_id if existing else None)
                ),
                condition=existing.condition if existing else None,
            )

    for exit_op in plan.exits:
        world.upsert_exit(
            str(exit_op["from_room_id"]),
            str(exit_op["direction"]),
            str(exit_op["to_room_id"]),
        )

    for attachment in plan.attachments:
        world.upsert_lore_key_ref(
            str(attachment["entity_kind"]),
            str(attachment["entity_id"]),
            str(attachment["lore_key"]),
        )

    plan.status = PLAN_STATUS_APPLIED
    plan.notes.append("Applied to SQLite after explicit admin approval.")
    return plan
