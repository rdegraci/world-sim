"""Presentation helpers for full description vs stable recap."""

from __future__ import annotations

from world_sim.db.world_store import WorldStore, derive_stable_recap
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_NPC,
    COLLECTION_ROOM,
    ChromaManager,
)


def npc_canonical_description(
    world: WorldStore,
    lore: ChromaManager,
    npc_id: str,
) -> str:
    npc = world.get_npc(npc_id)
    if npc is None:
        return ""
    chunks: list[str] = []
    for key in npc.npc_lore:
        text = lore.get_lore(COLLECTION_NPC, key)
        if text:
            chunks.append(text)
    if chunks:
        return "\n\n".join(chunks)
    return npc.name


def present_room(
    world: WorldStore,
    lore: ChromaManager,
    *,
    player_character_id: int,
    room_id: str,
    force_full: bool = False,
    show_pending_stubs: bool = False,
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
    exit_labels = list(sorted(exits))
    if show_pending_stubs:
        for direction in sorted(world.list_pending_stub_directions(room_id)):
            if direction not in exits:
                exit_labels.append(f"{direction} (frontier)")
    items = world.list_items_in_room(room_id)
    npcs = world.list_npcs_in_room(room_id)
    exit_text = ", ".join(exit_labels) if exit_labels else "none"
    if items:
        item_text = ", ".join(
            f"{item.name or 'item'} (#{item.id})" for item in items
        )
    else:
        item_text = "none visible"
    if npcs:
        npc_text = ", ".join(f"{npc.name} ({npc.npc_id})" for npc in npcs)
    else:
        npc_text = "none visible"

    return (
        f"{room.name}\n"
        f"{body}\n"
        f"Exits: {exit_text}\n"
        f"Items here: {item_text}\n"
        f"NPCs here: {npc_text}\n"
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


def present_npc(
    world: WorldStore,
    lore: ChromaManager,
    *,
    player_character_id: int,
    npc_id: str,
    force_full: bool = False,
) -> str:
    npc = world.get_npc(npc_id)
    if npc is None:
        return "There is no such NPC in current world state."

    full = npc_canonical_description(world, lore, npc_id) or npc.name
    seen, recap = world.get_npc_presentation(player_character_id, npc_id)
    if force_full or not seen:
        stable = recap or derive_stable_recap(full)
        world.mark_npc_full_description_seen(player_character_id, npc_id, stable)
        body = full
        mode = "full"
    else:
        body = recap or derive_stable_recap(full)
        if recap is None:
            world.mark_npc_full_description_seen(player_character_id, npc_id, body)
        mode = "recap"

    location = npc.current_room_id or "unplaced"
    condition = npc.condition or "ordinary"
    return (
        f"{npc.name} ({npc.npc_id})\n"
        f"{body}\n"
        f"Location: {location}\n"
        f"Condition: {condition}\n"
        f"Lore keys: {', '.join(npc.npc_lore) if npc.npc_lore else '(none)'}\n"
        f"[presentation={mode}]"
    )
