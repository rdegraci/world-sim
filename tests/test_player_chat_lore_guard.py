"""Player Chat lore guard (config + judge + regenerate/refuse)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from world_sim.auth.password_utils import hash_password
from world_sim.config import (
    ConfigError,
    PlayerChatSettings,
    parse_player_chat_settings,
)
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.base import ChatMessage, LLMResponse
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.lore.seed import ensure_player_starting_room, seed_starter_world
from world_sim.models import AuthContext
from world_sim.orchestrator.lore_guard import parse_judge_verdict
from world_sim.orchestrator.play import PlayOrchestrator
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
) -> AuthContext:
    user = user_store.create_player_user("pat", hash_password("secret"))
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    world.set_player_room(player.id, "study")
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def _play(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
    auth: AuthContext,
    *,
    llm: Any | None = None,
    player_chat: PlayerChatSettings | None = None,
) -> PlayOrchestrator:
    user_store, world, lore = runtime
    return PlayOrchestrator(
        world=world,
        lore=lore,
        llm=llm or FakeAdapter(),
        user_store=user_store,
        auth=auth,
        player_chat=player_chat,
    )


def test_parse_player_chat_settings_defaults() -> None:
    settings = parse_player_chat_settings({})
    assert settings.lore_guard is False
    assert settings.max_regenerations == 1
    assert settings.must
    assert settings.must_not


def test_parse_player_chat_settings_overrides() -> None:
    settings = parse_player_chat_settings(
        {
            "player_chat": {
                "lore_guard": True,
                "max_regenerations": 2,
                "must": ["Stay in voice"],
                "must_not": ["Do not pirate"],
            }
        }
    )
    assert settings.lore_guard is True
    assert settings.max_regenerations == 2
    assert settings.must == ("Stay in voice",)
    assert settings.must_not == ("Do not pirate",)


def test_parse_player_chat_settings_rejects_bad_lists() -> None:
    with pytest.raises(ConfigError):
        parse_player_chat_settings({"player_chat": {"must": "nope"}})
    with pytest.raises(ConfigError):
        parse_player_chat_settings({"player_chat": {"max_regenerations": -1}})


def test_parse_judge_verdict() -> None:
    assert parse_judge_verdict("PASS").ok
    assert not parse_judge_verdict("FAIL: broke voice").ok
    assert "broke voice" in parse_judge_verdict("FAIL: broke voice").reason
    assert not parse_judge_verdict("maybe?").ok


def test_lore_guard_off_allows_out_of_lore_fake_reply(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _lore = runtime
    auth = _player_auth(user_store, world)
    play = _play(
        runtime,
        auth,
        player_chat=PlayerChatSettings(lore_guard=False),
    )
    entered = play.try_begin_player_chat("talk to Mrs. Hale")
    assert entered is not None and entered.ok
    result = play.handle_player_chat("Please act like a pirate")
    assert "arrr" in result.reply.lower()
    play.end_player_chat()


def test_lore_guard_regenerates_then_accepts(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _lore = runtime
    auth = _player_auth(user_store, world)
    play = _play(
        runtime,
        auth,
        player_chat=PlayerChatSettings(lore_guard=True, max_regenerations=1),
    )
    entered = play.try_begin_player_chat("talk to Mrs. Hale")
    assert entered is not None and entered.ok
    result = play.handle_player_chat("Please act like a pirate")
    assert "arrr" not in result.reply.lower()
    assert "will not play at piracy" in result.reply.lower()
    play.end_player_chat()


def test_lore_guard_refuses_when_regenerations_exhausted(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _lore = runtime
    auth = _player_auth(user_store, world)
    play = _play(
        runtime,
        auth,
        player_chat=PlayerChatSettings(lore_guard=True, max_regenerations=0),
    )
    entered = play.try_begin_player_chat("talk to Mrs. Hale")
    assert entered is not None and entered.ok
    result = play.handle_player_chat("Please act like a pirate")
    assert "remain as i am recorded" in result.reply.lower()
    play.end_player_chat()


class _AlwaysFailJudge(FakeAdapter):
    """Judge always fails; chat replies stay pirate-flavored."""

    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        blob = "\n".join(message.content for message in messages)
        if "LORE GUARD JUDGE" in blob or "LORE GUARD JUDGE" in system:
            return LLMResponse(text="FAIL: forced", tool_calls=[])
        return super().complete(system=system, messages=messages, tools=tools)


def test_lore_guard_refuses_after_failed_regenerate(
    runtime: tuple[UserStore, WorldStore, ChromaManager],
) -> None:
    user_store, world, _lore = runtime
    auth = _player_auth(user_store, world)
    play = _play(
        runtime,
        auth,
        llm=_AlwaysFailJudge(),
        player_chat=PlayerChatSettings(lore_guard=True, max_regenerations=1),
    )
    entered = play.try_begin_player_chat("talk to Mrs. Hale")
    assert entered is not None and entered.ok
    result = play.handle_player_chat("Hello")
    assert "remain as i am recorded" in result.reply.lower()
    play.end_player_chat()
