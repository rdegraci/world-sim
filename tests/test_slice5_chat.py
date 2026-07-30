"""Slice 5 tests: chat_mode sandbox, NPC presentation, providers."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.auth.password_utils import hash_password
from world_sim.config import ConfigError, Settings, resolve_paths
from world_sim.db.draft_store import DraftStore
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.anthropic_adapter import AnthropicAdapter
from world_sim.llm.factory import create_llm_adapter
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.llm.grok_adapter import GrokAdapter
from world_sim.llm.openai_adapter import OpenAIAdapter
from world_sim.lore.chroma_manager import COLLECTION_NPC, ChromaManager
from world_sim.lore.seed import (
    DEFAULT_CHAT_NPC_ID,
    ensure_player_starting_room,
    seed_starter_world,
)
from world_sim.models import AuthContext
from world_sim.orchestrator.chat import ChatAccessError, ChatOrchestrator
from world_sim.orchestrator.edit import EditOrchestrator
from world_sim.orchestrator.presentation import present_npc
from world_sim.server.session_server import run_session
from world_sim.tools.implementations import PlayTools
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def runtime(tmp_path: Path) -> tuple[UserStore, WorldStore, DraftStore, ChromaManager]:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    user_store = UserStore(db.connection)
    world = WorldStore(db.connection)
    drafts = DraftStore(db.connection)
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(world, lore)
    return user_store, world, drafts, lore


def _admin_auth(user_store: UserStore, world: WorldStore) -> AuthContext:
    user = user_store.ensure_admin_user()
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def _player_auth(user_store: UserStore, world: WorldStore) -> AuthContext:
    user = user_store.create_player_user("morgan", hash_password("secret"))
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def _settings(tmp_path: Path, *, provider: str, **keys: str | None) -> Settings:
    paths = resolve_paths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    return Settings(
        paths=paths,
        provider=provider,
        log_level="INFO",
        grok_api_key=keys.get("grok_api_key") or "",
        openai_api_key=keys.get("openai_api_key"),
        anthropic_api_key=keys.get("anthropic_api_key"),
        admin_password="admin",
        raw_config={"provider": provider},
    )


def test_npc_mvp_shape_and_lore_linkage(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    _, world, _, lore = runtime
    npc = world.get_npc(DEFAULT_CHAT_NPC_ID)
    assert npc is not None
    assert npc.name == "Mrs. Hale"
    assert isinstance(npc.npc_lore, list)
    assert len(npc.npc_lore) >= 1
    for key in npc.npc_lore:
        assert lore.get_lore(COLLECTION_NPC, key)


def test_npc_presentation_full_recap_look(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id

    first = present_npc(
        world, lore, player_character_id=pc, npc_id=DEFAULT_CHAT_NPC_ID
    )
    assert "[presentation=full]" in first
    second = present_npc(
        world, lore, player_character_id=pc, npc_id=DEFAULT_CHAT_NPC_ID
    )
    assert "[presentation=recap]" in second
    looked = present_npc(
        world,
        lore,
        player_character_id=pc,
        npc_id=DEFAULT_CHAT_NPC_ID,
        force_full=True,
    )
    assert "[presentation=full]" in looked


def test_runtime_npc_condition_does_not_invalidate_seen(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id
    present_npc(world, lore, player_character_id=pc, npc_id=DEFAULT_CHAT_NPC_ID)
    seen_before, recap_before = world.get_npc_presentation(pc, DEFAULT_CHAT_NPC_ID)
    assert seen_before is True
    world.set_npc_condition(DEFAULT_CHAT_NPC_ID, "holding a ledger")
    seen_after, recap_after = world.get_npc_presentation(pc, DEFAULT_CHAT_NPC_ID)
    assert seen_after is True
    assert recap_after == recap_before


def test_npc_canon_edit_invalidates_presentation(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, drafts, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id
    present_npc(world, lore, player_character_id=pc, npc_id=DEFAULT_CHAT_NPC_ID)
    edit = EditOrchestrator(
        world=world,
        lore=lore,
        drafts=drafts,
        llm=FakeAdapter(),
        auth=auth,
    )
    result = edit.handle(
        "add_npc_lore mrs_hale | Mrs. Hale now wears a navy shawl and watches the door."
    )
    assert result.ok
    seen, recap = world.get_npc_presentation(pc, DEFAULT_CHAT_NPC_ID)
    assert seen is False
    assert recap is None


def test_chat_mode_admin_only(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _player_auth(user_store, world)
    chat = ChatOrchestrator(
        world=world,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
    )
    with pytest.raises(ChatAccessError):
        chat.handle("Hello")


def test_session_blocks_mode_chat_for_non_admin(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _player_auth(user_store, world)
    chat = ChatOrchestrator(
        world=world,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
    )
    outputs: list[str] = []
    inputs = iter(["mode chat", "quit"])
    code = run_session(
        auth=auth,
        store=user_store,
        chat=chat,
        input_fn=lambda _: next(inputs),
        output_fn=outputs.append,
    )
    assert code == 0
    assert any("admin-only" in line for line in outputs)


def test_chat_mode_does_not_mutate_world(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    chat = ChatOrchestrator(
        world=world,
        lore=lore,
        llm=FakeAdapter(),
        user_store=user_store,
        auth=auth,
    )
    before_npc = world.get_npc(DEFAULT_CHAT_NPC_ID)
    before_minutes = world.get_minutes_elapsed()
    before_inv = world.list_player_items(auth.player_character.id)
    before_lore = lore.get_lore(COLLECTION_NPC, before_npc.npc_lore[0])  # type: ignore[union-attr]

    result = chat.handle("Tell me a secret about a hidden elevator.")
    assert result.ok
    assert "Mrs. Hale" in result.message

    after_npc = world.get_npc(DEFAULT_CHAT_NPC_ID)
    assert after_npc == before_npc
    assert world.get_minutes_elapsed() == before_minutes
    assert world.list_player_items(auth.player_character.id) == before_inv
    assert lore.get_lore(COLLECTION_NPC, before_npc.npc_lore[0]) == before_lore  # type: ignore[union-attr]
    assert world.get_room("hidden_elevator") is None


def test_examine_npc_in_play(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    world.set_player_room(auth.player_character.id, "study")
    tools = PlayTools(world, lore, player_character_id=auth.player_character.id)
    result = tools.examine_npc({"npc_name": "hale"})
    assert result.ok
    assert "[presentation=full]" in result.message


def test_provider_factory_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORLD_SIM_LLM", raising=False)
    grok = create_llm_adapter(
        _settings(tmp_path, provider="grok", grok_api_key="gk")
    )
    assert isinstance(grok, GrokAdapter)

    openai = create_llm_adapter(
        _settings(tmp_path / "o", provider="openai", openai_api_key="ok")
    )
    assert isinstance(openai, OpenAIAdapter)

    anthropic = create_llm_adapter(
        _settings(tmp_path / "a", provider="anthropic", anthropic_api_key="ak")
    )
    assert isinstance(anthropic, AnthropicAdapter)

    monkeypatch.setenv("WORLD_SIM_LLM", "fake")
    fake = create_llm_adapter(
        _settings(tmp_path / "f", provider="grok", grok_api_key="gk")
    )
    assert isinstance(fake, FakeAdapter)


def test_provider_factory_requires_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORLD_SIM_LLM", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        create_llm_adapter(_settings(tmp_path, provider="openai"))
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        create_llm_adapter(_settings(tmp_path / "a", provider="anthropic"))
