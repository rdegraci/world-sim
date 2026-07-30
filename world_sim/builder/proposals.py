"""Propose structural seed-plan ops from approved lore and guidance briefs."""

from __future__ import annotations

from typing import Any

from world_sim.builder.brief import BriefError, load_guidance_brief
from world_sim.builder.linking import (
    display_name_from_id,
    entity_id_from_lore_key,
    get_lore_text,
    lore_exists,
)
from world_sim.builder.plans import SeedPlan, create_empty_plan
from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import ChromaManager


def propose_rooms_from_lore(
    plan: SeedPlan,
    lore: ChromaManager,
    world: WorldStore,
    lore_keys: list[str],
) -> SeedPlan:
    for key in lore_keys:
        key = key.strip()
        if not key:
            continue
        if not lore_exists(lore, key):
            plan.gaps.append(
                f"Missing approved room lore for '{key}' — not proposing (fail closed)."
            )
            continue
        room_id = entity_id_from_lore_key(key, kind="room")
        name = display_name_from_id(room_id)
        existing = world.get_room(room_id)
        action = "update" if existing else "create"
        _upsert_room_op(plan, room_id=room_id, name=name, lore_key=key, action=action)
        _upsert_attachment(plan, "room", room_id, key)
    return plan


def propose_items_from_lore(
    plan: SeedPlan,
    lore: ChromaManager,
    world: WorldStore,
    lore_keys: list[str],
    *,
    place_in: str | None = None,
) -> SeedPlan:
    for key in lore_keys:
        key = key.strip()
        if not key:
            continue
        if not lore_exists(lore, key):
            plan.gaps.append(
                f"Missing approved item lore for '{key}' — not proposing (fail closed)."
            )
            continue
        item_id = entity_id_from_lore_key(key, kind="item")
        name = display_name_from_id(item_id)
        existing = world.get_item_definition(item_id)
        action = "update" if existing else "create"
        _upsert_item_op(
            plan,
            item_id=item_id,
            name=name,
            lore_key=key,
            action=action,
            place_in=place_in,
        )
        _upsert_attachment(plan, "item_definition", item_id, key)
    return plan


def propose_npcs_from_lore(
    plan: SeedPlan,
    lore: ChromaManager,
    world: WorldStore,
    lore_keys: list[str],
    *,
    npc_id: str | None = None,
    name: str | None = None,
    current_room_id: str | None = None,
) -> SeedPlan:
    cleaned = [key.strip() for key in lore_keys if key.strip()]
    if not cleaned:
        return plan

    resolved_id = npc_id or entity_id_from_lore_key(cleaned[0], kind="npc")
    missing = [key for key in cleaned if not lore_exists(lore, key)]
    for key in missing:
        plan.gaps.append(
            f"Missing approved NPC lore for '{key}' — not attaching (fail closed)."
        )
    present = [key for key in cleaned if key not in missing]
    if not present:
        return plan

    display = name or display_name_from_id(resolved_id)
    existing = world.get_npc(resolved_id)
    action = "update" if existing else "create"
    if existing and not name:
        display = existing.name
    merged_lore = list(present)
    if existing:
        for key in existing.npc_lore:
            if key not in merged_lore and lore_exists(lore, key):
                merged_lore.append(key)
    _upsert_npc_op(
        plan,
        npc_id=resolved_id,
        name=display,
        npc_lore=merged_lore,
        action=action,
        current_room_id=current_room_id
        or (existing.current_room_id if existing else None),
    )
    for key in merged_lore:
        _upsert_attachment(plan, "npc", resolved_id, key)
    return plan


def propose_from_brief(
    lore: ChromaManager,
    world: WorldStore,
    brief_path: str,
) -> SeedPlan:
    """Load a guidance brief + current approved lore → draft seed plan only."""
    brief = load_guidance_brief(brief_path)
    plan = create_empty_plan(brief_path=str(brief_path), brief=brief)
    plan.notes.append(
        "Draft from guidance brief. Preview and validate before apply. Brief is not canon."
    )
    if brief.get("tone"):
        plan.notes.append(f"Brief tone (proposal flavor only): {brief['tone']}")
    if brief.get("goal"):
        plan.notes.append(f"Goal: {brief['goal']}")

    propose = brief.get("propose") or {}
    for entry in propose.get("rooms") or []:
        key = entry["lore_key"]
        if not lore_exists(lore, key):
            plan.gaps.append(
                f"Brief references room lore '{key}' not in approved Chroma — "
                "will not invent canon."
            )
            continue
        room_id = entry.get("room_id") or entity_id_from_lore_key(key, kind="room")
        name = entry.get("name") or display_name_from_id(room_id)
        existing = world.get_room(room_id)
        _upsert_room_op(
            plan,
            room_id=room_id,
            name=name,
            lore_key=key,
            action="update" if existing else "create",
        )
        _upsert_attachment(plan, "room", room_id, key)

    for entry in propose.get("items") or []:
        key = entry["lore_key"]
        if not lore_exists(lore, key):
            plan.gaps.append(
                f"Brief references item lore '{key}' not in approved Chroma — "
                "will not invent canon."
            )
            continue
        item_id = entry.get("item_id") or entity_id_from_lore_key(key, kind="item")
        name = entry.get("name") or display_name_from_id(item_id)
        existing = world.get_item_definition(item_id)
        _upsert_item_op(
            plan,
            item_id=item_id,
            name=name,
            lore_key=key,
            action="update" if existing else "create",
            place_in=entry.get("place_in"),
        )
        _upsert_attachment(plan, "item_definition", item_id, key)

    for entry in propose.get("npcs") or []:
        keys = list(entry.get("npc_lore") or [])
        missing = [key for key in keys if not lore_exists(lore, key)]
        for key in missing:
            plan.gaps.append(
                f"Brief references NPC lore '{key}' not in approved Chroma — "
                "will not invent canon."
            )
        present = [key for key in keys if key not in missing]
        if not present:
            continue
        npc_id = entry.get("npc_id") or entity_id_from_lore_key(present[0], kind="npc")
        name = entry.get("name") or display_name_from_id(npc_id)
        text = get_lore_text(lore, present[0])
        if text and not entry.get("name"):
            # Prefer a short name from id; lore remains descriptive text.
            pass
        existing = world.get_npc(npc_id)
        _upsert_npc_op(
            plan,
            npc_id=npc_id,
            name=name if not existing else (entry.get("name") or existing.name),
            npc_lore=present,
            action="update" if existing else "create",
            current_room_id=entry.get("current_room_id"),
        )
        for key in present:
            _upsert_attachment(plan, "npc", npc_id, key)

    for link in brief.get("must_link") or []:
        connect_rooms(
            plan,
            from_room_id=link["from"],
            direction=link["direction"],
            to_room_id=link["to"],
        )

    for placement in brief.get("must_place") or []:
        if placement["kind"] == "item":
            place_item(plan, placement["id"], placement["room"])
        elif placement["kind"] == "npc":
            place_npc(plan, placement["id"], placement["room"])

    return plan


def connect_rooms(
    plan: SeedPlan,
    *,
    from_room_id: str,
    direction: str,
    to_room_id: str,
) -> SeedPlan:
    direction_norm = direction.strip().lower()
    for exit_op in plan.exits:
        if (
            exit_op.get("from_room_id") == from_room_id
            and exit_op.get("direction") == direction_norm
        ):
            exit_op["to_room_id"] = to_room_id
            return plan
    plan.exits.append(
        {
            "from_room_id": from_room_id,
            "direction": direction_norm,
            "to_room_id": to_room_id,
        }
    )
    return plan


def place_item(plan: SeedPlan, item_id: str, room_id: str) -> SeedPlan:
    for item in plan.items:
        if item.get("item_id") == item_id:
            item["place_in"] = room_id
            return plan
    plan.items.append(
        {
            "item_id": item_id,
            "name": display_name_from_id(item_id),
            "lore_key": "",
            "action": "place_only",
            "place_in": room_id,
        }
    )
    return plan


def place_npc(plan: SeedPlan, npc_id: str, room_id: str) -> SeedPlan:
    for npc in plan.npcs:
        if npc.get("npc_id") == npc_id:
            npc["current_room_id"] = room_id
            return plan
    plan.npcs.append(
        {
            "npc_id": npc_id,
            "name": display_name_from_id(npc_id),
            "npc_lore": [],
            "action": "place_only",
            "current_room_id": room_id,
        }
    )
    return plan


def attach_lore(
    plan: SeedPlan,
    *,
    entity_kind: str,
    entity_id: str,
    lore_key: str,
) -> SeedPlan:
    _upsert_attachment(plan, entity_kind, entity_id, lore_key)
    if entity_kind == "room":
        for room in plan.rooms:
            if room.get("room_id") == entity_id:
                room["lore_key"] = lore_key
                return plan
        plan.rooms.append(
            {
                "room_id": entity_id,
                "name": display_name_from_id(entity_id),
                "lore_key": lore_key,
                "action": "attach_only",
            }
        )
    elif entity_kind in {"item", "item_definition"}:
        for item in plan.items:
            if item.get("item_id") == entity_id:
                item["lore_key"] = lore_key
                return plan
        plan.items.append(
            {
                "item_id": entity_id,
                "name": display_name_from_id(entity_id),
                "lore_key": lore_key,
                "action": "attach_only",
            }
        )
    elif entity_kind == "npc":
        for npc in plan.npcs:
            if npc.get("npc_id") == entity_id:
                lore_list = list(npc.get("npc_lore") or [])
                if lore_key not in lore_list:
                    lore_list.append(lore_key)
                npc["npc_lore"] = lore_list
                return plan
        plan.npcs.append(
            {
                "npc_id": entity_id,
                "name": display_name_from_id(entity_id),
                "npc_lore": [lore_key],
                "action": "attach_only",
            }
        )
    return plan


def _upsert_room_op(
    plan: SeedPlan,
    *,
    room_id: str,
    name: str,
    lore_key: str,
    action: str,
) -> None:
    for room in plan.rooms:
        if room.get("room_id") == room_id:
            room.update({"name": name, "lore_key": lore_key, "action": action})
            return
    plan.rooms.append(
        {"room_id": room_id, "name": name, "lore_key": lore_key, "action": action}
    )


def _upsert_item_op(
    plan: SeedPlan,
    *,
    item_id: str,
    name: str,
    lore_key: str,
    action: str,
    place_in: str | None = None,
) -> None:
    for item in plan.items:
        if item.get("item_id") == item_id:
            item.update({"name": name, "lore_key": lore_key, "action": action})
            if place_in:
                item["place_in"] = place_in
            return
    op: dict[str, Any] = {
        "item_id": item_id,
        "name": name,
        "lore_key": lore_key,
        "action": action,
    }
    if place_in:
        op["place_in"] = place_in
    plan.items.append(op)


def _upsert_npc_op(
    plan: SeedPlan,
    *,
    npc_id: str,
    name: str,
    npc_lore: list[str],
    action: str,
    current_room_id: str | None = None,
) -> None:
    for npc in plan.npcs:
        if npc.get("npc_id") == npc_id:
            npc.update({"name": name, "npc_lore": list(npc_lore), "action": action})
            if current_room_id is not None:
                npc["current_room_id"] = current_room_id
            return
    op: dict[str, Any] = {
        "npc_id": npc_id,
        "name": name,
        "npc_lore": list(npc_lore),
        "action": action,
    }
    if current_room_id is not None:
        op["current_room_id"] = current_room_id
    plan.npcs.append(op)


def _upsert_attachment(
    plan: SeedPlan,
    entity_kind: str,
    entity_id: str,
    lore_key: str,
) -> None:
    kind = "item_definition" if entity_kind == "item" else entity_kind
    for attachment in plan.attachments:
        if (
            attachment.get("entity_kind") == kind
            and attachment.get("entity_id") == entity_id
            and attachment.get("lore_key") == lore_key
        ):
            return
    plan.attachments.append(
        {"entity_kind": kind, "entity_id": entity_id, "lore_key": lore_key}
    )


# Re-export BriefError for callers
__all__ = [
    "BriefError",
    "attach_lore",
    "connect_rooms",
    "place_item",
    "place_npc",
    "propose_from_brief",
    "propose_items_from_lore",
    "propose_npcs_from_lore",
    "propose_rooms_from_lore",
]
