"""Slice 3 tests: lore, presentation, tools, and grounded play."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.auth.password_utils import hash_password
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore, derive_stable_recap
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.lore.chroma_manager import (
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)
from world_sim.lore.seed import (
    START_ROOM_ID,
    SYSTEM_LORE_KEY,
    ensure_player_starting_room,
    seed_starter_world,
)
from world_sim.models import AuthContext
from world_sim.orchestrator.context_builder import ContextBuilder
from world_sim.orchestrator.play import PlayOrchestrator
from world_sim.orchestrator.presentation import present_item, present_room
from world_sim.tools.implementations import PlayTools
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def runtime(tmp_path: Path) -> tuple[UserStore, WorldStore, ChromaManager]:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    user_store = UserStore(db.connection)
    world = WorldStore(db.connection)
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(world, lore)
    return user_store, world, lore


def _auth(user_store: UserStore, world: WorldStore, username: str = "player1") -> AuthContext:
    user = user_store.create_player_user(username, hash_password("secret"))
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def test_chroma_system_lore_roundtrip(runtime: tuple[UserStore, WorldStore, ChromaManager]) -> None:
    _, _, lore = runtime
    text = lore.get_lore(COLLECTION_SYSTEM, SYSTEM_LORE_KEY)
    assert text is not None
    assert "Quiet Manor" in text


def test_explicit_lore_key_refs_and_context(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, lore = runtime
    auth = _auth(user_store, world)
    keys = world.list_lore_keys("room", "foyer")
    assert "room:foyer" in keys

    context = ContextBuilder(world, lore).build(auth.player_character.id)
    assert SYSTEM_LORE_KEY in context.text
    assert "room:foyer" in context.text
    assert "SQLite first" in context.text
    room_lore = lore.get_lore(COLLECTION_ROOM, "room:foyer")
    assert room_lore is not None
    assert room_lore in context.text


def test_room_full_then_recap_then_look(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, lore = runtime
    auth = _auth(user_store, world)
    pc = auth.player_character.id

    first = present_room(world, lore, player_character_id=pc, room_id="foyer")
    assert "[presentation=full]" in first
    assert "narrow welcome hall" in first

    second = present_room(world, lore, player_character_id=pc, room_id="foyer")
    assert "[presentation=recap]" in second
    seen, recap = world.get_room_presentation(pc, "foyer")
    assert seen is True
    assert recap is not None
    assert recap in second

    looked = present_room(
        world,
        lore,
        player_character_id=pc,
        room_id="foyer",
        force_full=True,
    )
    assert "[presentation=full]" in looked
    assert "narrow welcome hall" in looked


def test_runtime_move_does_not_invalidate_seen_state(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, lore = runtime
    auth = _auth(user_store, world)
    pc = auth.player_character.id
    present_room(world, lore, player_character_id=pc, room_id="foyer")
    seen_before, recap_before = world.get_room_presentation(pc, "foyer")
    assert seen_before is True

    tools = PlayTools(world, lore, player_character_id=pc)
    moved = tools.move_player({"direction": "north"})
    assert moved.ok
    assert world.get_player_room_id(pc) == "hallway"

    seen_after, recap_after = world.get_room_presentation(pc, "foyer")
    assert seen_after is True
    assert recap_after == recap_before

    # Returning to foyer should still use recap.
    back = tools.move_player({"direction": "south"})
    assert back.ok
    assert "[presentation=recap]" in back.message


def test_take_item_updates_inventory(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, lore = runtime
    auth = _auth(user_store, world)
    pc = auth.player_character.id
    tools = PlayTools(world, lore, player_character_id=pc)

    result = tools.take_item({"item_name": "brass key"})
    assert result.ok
    inventory = world.list_player_items(pc)
    assert len(inventory) == 1
    assert inventory[0].name == "brass key"
    assert inventory[0].location_kind == "player_character"
    assert world.list_items_in_room("foyer") == []


def test_item_examine_full_vs_recap(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, lore = runtime
    auth = _auth(user_store, world)
    pc = auth.player_character.id
    tools = PlayTools(world, lore, player_character_id=pc)
    tools.take_item({"item_name": "key"})
    item = world.list_player_items(pc)[0]

    first = present_item(
        world,
        lore,
        player_character_id=pc,
        item_instance_id=item.id,
    )
    assert "[presentation=full]" in first
    second = present_item(
        world,
        lore,
        player_character_id=pc,
        item_instance_id=item.id,
    )
    assert "[presentation=recap]" in second
    examined = present_item(
        world,
        lore,
        player_character_id=pc,
        item_instance_id=item.id,
        force_full=True,
    )
    assert "[presentation=full]" in examined


def test_play_orchestrator_move_and_false_assertion(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, lore = runtime
    auth = _auth(user_store, world, username="explorer")
    play = PlayOrchestrator(
        world=world,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
    )

    moved = play.handle_action("go north")
    assert "move_player" in moved.tool_names
    assert world.get_player_room_id(auth.player_character.id) == "hallway"

    refused = play.handle_action("there is a dragon here")
    assert refused.tool_names == []
    assert "DM:" in refused.reply
    assert world.get_room("dragon_lair") is None


def test_advance_time_tool(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, lore = runtime
    auth = _auth(user_store, world)
    tools = PlayTools(world, lore, player_character_id=auth.player_character.id)
    assert world.get_minutes_elapsed() == 0
    result = tools.advance_time({"minutes": 15})
    assert result.ok
    assert world.get_minutes_elapsed() == 15


def test_derive_stable_recap_is_stable() -> None:
    text = "The foyer is narrow. Dust floats in the light."
    assert derive_stable_recap(text) == "The foyer is narrow."


def test_seed_is_idempotent(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    _, world, lore = runtime
    assert seed_starter_world(world, lore) is False
    assert world.get_room(START_ROOM_ID) is not None
