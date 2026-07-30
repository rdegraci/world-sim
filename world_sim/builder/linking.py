"""Lore-key helpers and entity id derivation for Builder proposals."""

from __future__ import annotations

from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_NPC,
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)

COLLECTION_BY_PREFIX = {
    "system": COLLECTION_SYSTEM,
    "room": COLLECTION_ROOM,
    "item": COLLECTION_ITEM,
    "npc": COLLECTION_NPC,
}


def collection_for_lore_key(lore_key: str) -> str | None:
    prefix = lore_key.split(":", 1)[0].strip().lower()
    return COLLECTION_BY_PREFIX.get(prefix)


def lore_exists(lore: ChromaManager, lore_key: str) -> bool:
    collection = collection_for_lore_key(lore_key)
    if collection is None:
        return False
    return lore.get_lore(collection, lore_key) is not None


def get_lore_text(lore: ChromaManager, lore_key: str) -> str | None:
    collection = collection_for_lore_key(lore_key)
    if collection is None:
        return None
    return lore.get_lore(collection, lore_key)


def entity_id_from_lore_key(lore_key: str, *, kind: str) -> str:
    """Derive a stable SQLite id from an approved lore key."""
    parts = lore_key.strip().split(":")
    if kind == "npc":
        if len(parts) >= 2 and parts[0] == "npc":
            return parts[1]
        return lore_key.replace(":", "_")
    if len(parts) >= 2 and parts[0] == kind:
        return parts[1]
    return parts[-1] if parts else lore_key


def display_name_from_id(entity_id: str) -> str:
    return entity_id.replace("_", " ").strip().title()


def expected_prefix_for_entity(entity_kind: str) -> str | None:
    mapping = {
        "room": "room",
        "item_definition": "item",
        "item": "item",
        "npc": "npc",
        "system": "system",
    }
    return mapping.get(entity_kind)


def hierarchy_conflict(entity_kind: str, lore_key: str) -> str | None:
    """Return an error if lore-key prefix conflicts with entity kind hierarchy."""
    expected = expected_prefix_for_entity(entity_kind)
    if expected is None:
        return None
    prefix = lore_key.split(":", 1)[0].strip().lower()
    if prefix != expected:
        return (
            f"Hierarchy conflict: {entity_kind} '{lore_key}' should use "
            f"'{expected}:' prefix (got '{prefix}:')."
        )
    return None
