"""Phase 2d: dynamic frontier expansion and campaign identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.auth.password_utils import hash_password
from world_sim.builder.realize import RealizeError, realize_adjacent
from world_sim.config import (
    WorldExpansionSettings,
    parse_world_expansion_settings,
)
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.lore.chroma_manager import COLLECTION_ROOM, ChromaManager
from world_sim.lore.seed import ensure_player_starting_room, seed_starter_world
from world_sim.models import AuthContext
from world_sim.orchestrator.play import PlayOrchestrator
from world_sim.tools.implementations import PlayTools
from world_sim.utils.logger import reset_logging_for_tests, setup_logging

GARDEN_LORE = (
    "A walled kitchen garden of damp earth and clipped rosemary, "
    "reached by a narrow door from the hallway."
)


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def runtime(tmp_path: Path) -> tuple[UserStore, WorldStore, ChromaManager, Path]:
    db_path = tmp_path / "world.sqlite3"
    db = SqliteManager(db_path)
    db.initialize_schema()
    user_store = UserStore(db.connection)
    world = WorldStore(db.connection)
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(world, lore)
    return user_store, world, lore, db_path


def _auth(user_store: UserStore, world: WorldStore) -> AuthContext:
    user = user_store.create_player_user("pat", hash_password("secret"))
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    world.set_player_room(player.id, "hallway")
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def _seed_garden_stub(world: WorldStore, lore: ChromaManager) -> None:
    lore.upsert_lore(COLLECTION_ROOM, "room:garden", GARDEN_LORE)
    world.upsert_frontier_stub(
        stub_id="stub_hallway_east_garden",
        from_room_id="hallway",
        direction="west",
        target_room_id="garden",
        target_name="Kitchen Garden",
        lore_key="room:garden",
        return_direction="east",
    )


def test_config_defaults_expansion_off() -> None:
    settings = parse_world_expansion_settings({})
    assert settings.dynamic_expansion is False
    assert settings.require_brief_or_stub is True
    assert settings.max_new_rooms_per_session == 5

    on = parse_world_expansion_settings(
        {"world": {"dynamic_expansion": True, "max_new_rooms_per_session": 2}}
    )
    assert on.dynamic_expansion is True
    assert on.max_new_rooms_per_session == 2


def test_expansion_off_blocks_stub(
    runtime: tuple[UserStore, WorldStore, ChromaManager, Path],
) -> None:
    user_store, world, lore, _ = runtime
    auth = _auth(user_store, world)
    _seed_garden_stub(world, lore)
    tools = PlayTools(
        world,
        lore,
        player_character_id=auth.player_character.id,
        expansion=WorldExpansionSettings(dynamic_expansion=False),
    )
    result = tools.move_player({"direction": "west"})
    assert not result.ok
    assert "sealed" in result.message.lower() or "expansion is off" in result.message.lower()
    assert world.get_room("garden") is None
    stub = world.get_frontier_stub("stub_hallway_east_garden")
    assert stub is not None
    assert stub.status == "pending"


def test_expansion_on_realizes_once_and_persists(
    runtime: tuple[UserStore, WorldStore, ChromaManager, Path],
) -> None:
    user_store, world, lore, db_path = runtime
    auth = _auth(user_store, world)
    _seed_garden_stub(world, lore)
    expansion = WorldExpansionSettings(dynamic_expansion=True)
    tools = PlayTools(
        world,
        lore,
        player_character_id=auth.player_character.id,
        expansion=expansion,
    )
    result = tools.move_player({"direction": "west"})
    assert result.ok, result.message
    assert world.get_room("garden") is not None
    assert world.list_exits("hallway").get("west") == "garden"
    assert world.list_exits("garden").get("east") == "hallway"
    stub = world.get_frontier_stub("stub_hallway_east_garden")
    assert stub is not None and stub.status == "realized"
    events = world.list_runtime_events(event_type="room_realized")
    assert events

    # Campaign identity: reopen DB with expansion OFF — room remains.
    db2 = SqliteManager(db_path)
    db2.initialize_schema()
    world2 = WorldStore(db2.connection)
    assert world2.get_room("garden") is not None
    assert world2.list_exits("hallway").get("west") == "garden"
    stub2 = world2.get_frontier_stub("stub_hallway_east_garden")
    assert stub2 is not None and stub2.status == "realized"


def test_contradicting_missing_lore_rejected(
    runtime: tuple[UserStore, WorldStore, ChromaManager, Path],
) -> None:
    _user_store, world, lore, _ = runtime
    world.upsert_frontier_stub(
        stub_id="stub_bad",
        from_room_id="hallway",
        direction="north",
        target_room_id="void",
        target_name="Void",
        lore_key="room:does_not_exist",
        return_direction="south",
    )
    stub = world.get_frontier_stub("stub_bad")
    assert stub is not None
    with pytest.raises(RealizeError, match="Fail closed|missing"):
        realize_adjacent(
            world,
            lore,
            stub,
            settings=WorldExpansionSettings(dynamic_expansion=True),
        )
    assert world.get_room("void") is None


def test_narration_cannot_create_rooms_via_play_tools_without_stub(
    runtime: tuple[UserStore, WorldStore, ChromaManager, Path],
) -> None:
    user_store, world, lore, _ = runtime
    auth = _auth(user_store, world)
    play = PlayOrchestrator(
        world=world,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
        expansion=WorldExpansionSettings(dynamic_expansion=True),
    )
    # FakeAdapter move west with no exit and no stub — refusal, no room created.
    result = play.handle_action("go west")
    assert world.get_room("garden") is None
    assert "no such passage" in result.reply.lower() or result.tool_names


def test_disable_switch_keeps_realized_room(
    runtime: tuple[UserStore, WorldStore, ChromaManager, Path],
) -> None:
    user_store, world, lore, _ = runtime
    auth = _auth(user_store, world)
    _seed_garden_stub(world, lore)
    tools_on = PlayTools(
        world,
        lore,
        player_character_id=auth.player_character.id,
        expansion=WorldExpansionSettings(dynamic_expansion=True),
    )
    assert tools_on.move_player({"direction": "west"}).ok
    world.set_player_room(auth.player_character.id, "hallway")

    tools_off = PlayTools(
        world,
        lore,
        player_character_id=auth.player_character.id,
        expansion=WorldExpansionSettings(dynamic_expansion=False),
    )
    # Real exit still works with expansion off.
    again = tools_off.move_player({"direction": "west"})
    assert again.ok
    assert world.get_player_room_id(auth.player_character.id) == "garden"


def test_direct_go_west_realizes_frontier_without_llm(
    runtime: tuple[UserStore, WorldStore, ChromaManager, Path],
) -> None:
    user_store, world, lore, _ = runtime
    auth = _auth(user_store, world)
    _seed_garden_stub(world, lore)
    play = PlayOrchestrator(
        world=world,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
        expansion=WorldExpansionSettings(dynamic_expansion=True),
    )
    result = play.handle_action("go west")
    assert "lasting passage" in result.reply.lower() or "Kitchen Garden" in result.reply
    assert world.get_room("garden") is not None
    assert "move_player" in result.tool_names
