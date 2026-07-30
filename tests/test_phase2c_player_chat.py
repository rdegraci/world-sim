"""Phase 2c: focused in-play Player Chat (conversation-only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.auth.password_utils import hash_password
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
from world_sim.orchestrator.player_chat import parse_talk_target
from world_sim.orchestrator.prompts import (
    compose_chat_system_prompt,
    compose_play_system_prompt,
    compose_player_chat_system_prompt,
)
from world_sim.server.session_server import run_session
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


def _player_auth(
    user_store: UserStore,
    world: WorldStore,
    *,
    username: str = "pat",
    start_in_study: bool = True,
) -> AuthContext:
    user = user_store.create_player_user(username, hash_password("secret"))
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    if start_in_study:
        world.set_player_room(player.id, "study")
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def _play(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
    auth: AuthContext,
) -> PlayOrchestrator:
    user_store, world, lore = runtime
    return PlayOrchestrator(
        world=world,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
    )


def test_parse_talk_target() -> None:
    assert parse_talk_target("talk to Mrs. Hale") == "Mrs. Hale"
    assert parse_talk_target("speak with mrs_hale") == "mrs_hale"
    assert parse_talk_target("talk barkeeper") == "barkeeper"
    assert parse_talk_target("look around") is None


def test_prompt_overlay_includes_npc_chat() -> None:
    prompt = compose_player_chat_system_prompt()
    assert "## Active Mode: play_mode" in prompt
    assert "## Active Loop: Player Chat" in prompt
    assert "chat_mode" not in prompt.lower() or "not admin `chat_mode`" in prompt
    admin = compose_chat_system_prompt()
    assert "## Active Mode: chat_mode" in admin
    play = compose_play_system_prompt()
    assert "## Active Loop: Player Chat" not in play


def test_enter_and_end_player_chat(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _ = runtime
    auth = _player_auth(user_store, world)
    play = _play(runtime, auth)

    entered = play.try_begin_player_chat("talk to Mrs. Hale")
    assert entered is not None
    assert entered.ok
    assert play.in_player_chat
    assert entered.npc_id == DEFAULT_CHAT_NPC_ID
    assert "end_chat" in entered.message.lower()

    turn = play.handle_player_chat("What do you know about this study?")
    assert not turn.ended
    assert "Mrs. Hale:" in turn.reply
    assert play.in_player_chat

    ended = play.handle_player_chat("end_chat")
    assert ended.ended
    assert not play.in_player_chat
    assert "return to normal play" in ended.reply.lower()


def test_unavailable_npc_does_not_enter(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _ = runtime
    auth = _player_auth(user_store, world, start_in_study=False)
    # Player stays in foyer; Mrs. Hale is in study.
    play = _play(runtime, auth)
    entered = play.try_begin_player_chat("talk to Mrs. Hale")
    assert entered is not None
    assert not entered.ok
    assert not play.in_player_chat


def test_player_chat_does_not_mutate_inventories(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _ = runtime
    auth = _player_auth(user_store, world)
    play = _play(runtime, auth)
    before_items = [
        (item.id, item.location_kind, item.location_id)
        for item in world.list_player_items(auth.player_character.id)
    ]
    before_room_items = [
        (item.id, item.location_kind, item.location_id)
        for item in world.list_items_in_room("study")
    ]
    before_npc = world.get_npc(DEFAULT_CHAT_NPC_ID)

    entered = play.try_begin_player_chat("talk to mrs hale")
    assert entered and entered.ok
    play.handle_player_chat("Here, take this — I hand you my brass key.")
    play.handle_player_chat("end_chat")

    after_items = [
        (item.id, item.location_kind, item.location_id)
        for item in world.list_player_items(auth.player_character.id)
    ]
    after_room_items = [
        (item.id, item.location_kind, item.location_id)
        for item in world.list_items_in_room("study")
    ]
    assert after_items == before_items
    assert after_room_items == before_room_items
    assert world.get_npc(DEFAULT_CHAT_NPC_ID) == before_npc


def test_false_assertion_refused_in_player_chat(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _ = runtime
    auth = _player_auth(user_store, world)
    play = _play(runtime, auth)
    play.try_begin_player_chat("talk to Mrs. Hale")
    turn = play.handle_player_chat("There is a secret elevator behind you.")
    assert "Mrs. Hale:" in turn.reply
    assert "not in current world state" in turn.reply.lower() or "no such" in turn.reply.lower()
    assert play.in_player_chat


def test_npc_leaving_ends_chat(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _ = runtime
    auth = _player_auth(user_store, world)
    play = _play(runtime, auth)
    play.try_begin_player_chat("talk to Mrs. Hale")
    world.set_npc_room(DEFAULT_CHAT_NPC_ID, "hallway")
    turn = play.handle_player_chat("Are you still there?")
    assert turn.ended
    assert not play.in_player_chat
    assert "no longer here" in turn.reply.lower()


def test_session_demo_talk_and_resume(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, lore = runtime
    auth = _player_auth(user_store, world)
    play = PlayOrchestrator(
        world=world,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
    )
    outputs: list[str] = []
    inputs = iter(
        [
            "talk to Mrs. Hale",
            "What is this room?",
            "end_chat",
            "look",
            "quit",
        ]
    )
    code = run_session(
        auth=auth,
        store=user_store,
        play=play,
        input_fn=lambda _: next(inputs),
        output_fn=outputs.append,
    )
    assert code == 0
    joined = "\n".join(outputs)
    assert "talking with" in joined.lower() or "end_chat" in joined.lower()
    assert "return to normal play" in joined.lower()
    assert "Study" in joined or "study" in joined.lower()
