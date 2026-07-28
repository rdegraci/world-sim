"""Presentation helpers for full description vs stable recap."""

from __future__ import annotations

from world_sim.db.world_store import WorldStore, derive_stable_recap
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_ROOM,
    ChromaManager,
)


def present_room(
    world: WorldStore,
    lore: ChromaManager,
    *,
    player_character_id: int,
    room_id: str,
    force_full: bool = False,
) -> str:
    room = world.get_room(room_id)
    if room is None:
        return "You are somewhere unmarked by the world records."

    full = lore.get_lore(COLLECTION_ROOM, room.lore_key) or room.name
    seen, recap = world.get_room_presentation(player_character_id, room_id)

    if force_full or not seen:
        stable = recap or derive_stable_recap(full)
        world.mark_room_full_description_seen(player_character_id, room_id, stable)
        body = full
        mode = "full"
    else:
        body = recap or derive_stable_recap(full)
        if recap is None:
            world.mark_room_full_description_seen(player_character_id, room_id, body)
        mode = "recap"

    exits = world.list_exits(room_id)
    items = world.list_items_in_room(room_id)
    exit_text = ", ".join(sorted(exits)) if exits else "none"
    if items:
        item_text = ", ".join(
            f"{item.name or 'item'} (#{item.id})" for item in items
        )
    else:
        item_text = "none visible"

    return (
        f"{room.name}\n"
        f"{body}\n"
        f"Exits: {exit_text}\n"
        f"Items here: {item_text}\n"
        f"[presentation={mode}]"
    )


def present_item(
    world: WorldStore,
    lore: ChromaManager,
    *,
    player_character_id: int,
    item_instance_id: int,
    force_full: bool = False,
) -> str:
    item = world.get_item_instance(item_instance_id)
    if item is None:
        return "There is no such item in current world state."

    lore_key = item.definition_key
    if not lore_key and item.item_definition_id:
        definition = world.get_item_definition(item.item_definition_id)
        lore_key = definition.lore_key if definition else None
    full = (
        lore.get_lore(COLLECTION_ITEM, lore_key)
        if lore_key
        else None
    ) or (item.name or f"item #{item.id}")

    seen, recap = world.get_item_presentation(player_character_id, item_instance_id)
    if force_full or not seen:
        stable = recap or derive_stable_recap(full)
        world.mark_item_full_description_seen(
            player_character_id,
            item_instance_id,
            stable,
        )
        body = full
        mode = "full"
    else:
        body = recap or derive_stable_recap(full)
        if recap is None:
            world.mark_item_full_description_seen(
                player_character_id,
                item_instance_id,
                body,
            )
        mode = "recap"

    location = f"{item.location_kind}:{item.location_id}"
    condition = item.condition or "ordinary"
    return (
        f"{item.name or f'item #{item.id}'}\n"
        f"{body}\n"
        f"Location: {location}\n"
        f"Condition: {condition}\n"
        f"[presentation={mode}]"
    )
