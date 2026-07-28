"""Hand-seeded starter world for Slice 3 grounded play."""

from __future__ import annotations

from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)
from world_sim.utils.logger import get_logger

SEED_FLAG = "starter_world_v1"

SYSTEM_LORE_KEY = "system:quiet_manor"
SYSTEM_LORE_TEXT = (
    "The Quiet Manor is a small, carefully kept house where memory lingers in "
    "wood polish and dusty sunlight. Hard facts about rooms, doors, and objects "
    "are recorded in structured world state. Lore describes meaning and "
    "atmosphere, not mutable placement."
)

ROOMS = [
    (
        "foyer",
        "Foyer",
        "room:foyer",
        (
            "The foyer is a narrow welcome hall of dark wood and muted green wallpaper. "
            "A brass coat hook gleams beside the door, and a thin runner leads toward "
            "the rest of the house. Dust motes hang in the late light from a high window."
        ),
    ),
    (
        "hallway",
        "Hallway",
        "room:hallway",
        (
            "The hallway runs straight and spare, lined with closed doors and a single "
            "faded carpet. Floorboards creak underfoot, and a cool draft moves from "
            "the east toward the foyer behind you."
        ),
    ),
    (
        "study",
        "Study",
        "room:study",
        (
            "The study smells of paper and old leather. A desk faces a shuttered window, "
            "and shelves lean with unlabeled binders. A lamp with a green glass shade "
            "throws a small circle of careful light."
        ),
    ),
]

EXITS = [
    ("foyer", "north", "hallway"),
    ("hallway", "south", "foyer"),
    ("hallway", "east", "study"),
    ("study", "west", "hallway"),
]

ITEMS = [
    (
        "brass_key",
        "brass key",
        "item:brass_key",
        (
            "A short brass key with a worn bow and a single clean tooth. It looks "
            "ordinary, but the metal is warm from recent handling."
        ),
        "foyer",
    ),
    (
        "worn_journal",
        "worn journal",
        "item:worn_journal",
        (
            "A cloth-bound journal with rounded corners and a ribbon marker. The first "
            "pages are filled with neat notes about doors, keys, and quiet rooms."
        ),
        "study",
    ),
]

START_ROOM_ID = "foyer"


def seed_starter_world(world: WorldStore, lore: ChromaManager) -> bool:
    """Seed the starter manor if not already present. Returns True if seeded now."""
    if world.get_meta(SEED_FLAG) == "1":
        return False

    logger = get_logger("seed")
    lore.upsert_lore(COLLECTION_SYSTEM, SYSTEM_LORE_KEY, SYSTEM_LORE_TEXT)
    world.upsert_lore_key_ref("system", "world", SYSTEM_LORE_KEY)

    for room_id, name, lore_key, text in ROOMS:
        lore.upsert_lore(COLLECTION_ROOM, lore_key, text)
        world.upsert_room(room_id, name, lore_key)

    for from_room, direction, to_room in EXITS:
        world.upsert_exit(from_room, direction, to_room)

    for item_id, name, lore_key, text, room_id in ITEMS:
        lore.upsert_lore(COLLECTION_ITEM, lore_key, text)
        world.upsert_item_definition(item_id, name, lore_key)
        world.create_item_instance(
            item_definition_id=item_id,
            location_kind="room",
            location_id=room_id,
        )

    world.set_meta(SEED_FLAG, "1")
    logger.info("Seeded starter world Quiet Manor (foyer/hallway/study).")
    return True


def ensure_player_starting_room(world: WorldStore, player_character_id: int) -> str:
    """Place the player in the foyer if they have no current room."""
    current = world.get_player_room_id(player_character_id)
    if current:
        return current
    world.set_player_room(player_character_id, START_ROOM_ID)
    return START_ROOM_ID
