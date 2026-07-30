"""Phase 3a: WorldAuthority port and runtime event substrate."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.auth.password_utils import hash_password
from world_sim.authority import (
    CHARACTER_ENTERED_ROOM,
    CHARACTER_LEFT_ROOM,
    ITEM_TAKEN,
    NPC_MOVED,
    TIME_ADVANCED,
    RuntimeEvent,
    WorldAuthority,
)
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.lore.seed import (
    DEFAULT_CHAT_NPC_ID,
    ensure_player_starting_room,
    seed_starter_world,
)
from world_sim.models import AuthContext
from world_sim.orchestrator.play import PlayOrchestrator
from world_sim.tools.implementations import PlayTools
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def runtime(tmp_path: Path) -> tuple[UserStore, WorldStore, WorldAuthority, ChromaManager]:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    user_store = UserStore(db.connection)
    store = WorldStore(db.connection)
    authority = WorldAuthority(store)
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(store, lore)
    return user_store, store, authority, lore


def _auth(user_store: UserStore, store: WorldStore, username: str = "player1") -> AuthContext:
    user = user_store.create_player_user(username, hash_password("secret"))
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(store, player.id)
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def test_play_tools_mutate_only_via_authority_port(
    runtime: tuple[UserStore, WorldStore, WorldAuthority, ChromaManager],
) -> None:
    """PlayTools always binds WorldAuthority; contested mutations emit via the port."""
    user_store, store, _authority, lore = runtime
    auth = _auth(user_store, store)
    pc = auth.player_character.id

    tools = PlayTools(store, lore, player_character_id=pc)
    assert isinstance(tools.world, WorldAuthority)
    assert tools.world.store is store

    # Bypass would be tools calling store.move_player without events — assert events fire.
    seen: list[RuntimeEvent] = []
    tools.world.events.subscribe(seen.append)
    assert tools.move_player({"direction": "north"}).ok
    assert any(e.event_type == CHARACTER_ENTERED_ROOM for e in seen)

    # Direct store mutation does not go through the bus.
    seen.clear()
    store.set_player_room(pc, "foyer")
    assert not seen


def test_move_emits_enter_and_leave_events(
    runtime: tuple[UserStore, WorldStore, WorldAuthority, ChromaManager],
) -> None:
    user_store, store, authority, lore = runtime
    auth = _auth(user_store, store)
    pc = auth.player_character.id
    seen: list[RuntimeEvent] = []
    authority.events.subscribe(seen.append)

    tools = PlayTools(authority, lore, player_character_id=pc)
    result = tools.move_player({"direction": "north"})
    assert result.ok
    assert store.get_player_room_id(pc) == "hallway"

    types = [e.event_type for e in seen]
    assert CHARACTER_LEFT_ROOM in types
    assert CHARACTER_ENTERED_ROOM in types
    left = next(e for e in seen if e.event_type == CHARACTER_LEFT_ROOM)
    entered = next(e for e in seen if e.event_type == CHARACTER_ENTERED_ROOM)
    assert left.payload["room_id"] == "foyer"
    assert left.payload["to_room_id"] == "hallway"
    assert left.payload["player_character_id"] == pc
    assert entered.payload["room_id"] == "hallway"
    assert entered.payload["from_room_id"] == "foyer"
    assert entered.room_ids == ("hallway",)

    persisted = authority.events.list_events(event_type=CHARACTER_ENTERED_ROOM, limit=5)
    assert any(e.payload.get("room_id") == "hallway" for e in persisted)


def test_take_emits_item_taken_event(
    runtime: tuple[UserStore, WorldStore, WorldAuthority, ChromaManager],
) -> None:
    user_store, store, authority, lore = runtime
    auth = _auth(user_store, store)
    pc = auth.player_character.id
    seen: list[RuntimeEvent] = []
    authority.events.subscribe(seen.append)

    tools = PlayTools(authority, lore, player_character_id=pc)
    result = tools.take_item({"item_name": "brass key"})
    assert result.ok

    taken = [e for e in seen if e.event_type == ITEM_TAKEN]
    assert len(taken) == 1
    assert taken[0].payload["room_id"] == "foyer"
    assert taken[0].payload["player_character_id"] == pc
    assert taken[0].payload["name"] == "brass key"
    assert "foyer" in taken[0].room_ids


def test_advance_time_and_npc_move_emit_events(
    runtime: tuple[UserStore, WorldStore, WorldAuthority, ChromaManager],
) -> None:
    user_store, store, authority, lore = runtime
    auth = _auth(user_store, store)
    seen: list[RuntimeEvent] = []
    authority.events.subscribe(seen.append)

    tools = PlayTools(authority, lore, player_character_id=auth.player_character.id)
    result = tools.advance_time({"minutes": 15})
    assert result.ok
    assert store.get_minutes_elapsed() == 15
    assert any(e.event_type == TIME_ADVANCED for e in seen)

    npc = store.get_npc(DEFAULT_CHAT_NPC_ID)
    assert npc is not None
    from_room = npc.current_room_id
    target = "hallway" if from_room != "hallway" else "foyer"
    authority.set_npc_room(npc.npc_id, target)
    moved = [e for e in seen if e.event_type == NPC_MOVED]
    assert moved
    assert moved[-1].payload["npc_id"] == npc.npc_id
    assert moved[-1].payload["to_room_id"] == target


def test_single_player_play_still_works_via_authority(
    runtime: tuple[UserStore, WorldStore, WorldAuthority, ChromaManager],
) -> None:
    user_store, store, authority, lore = runtime
    auth = _auth(user_store, store, username="explorer")
    play = PlayOrchestrator(
        world=authority,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
    )
    opening = play.opening_presentation()
    assert opening
    moved = play.handle_action("go north")
    assert "move_player" in moved.tool_names
    assert store.get_player_room_id(auth.player_character.id) == "hallway"
    events = authority.events.list_events(event_type=CHARACTER_ENTERED_ROOM, limit=5)
    assert any(e.payload.get("room_id") == "hallway" for e in events)
