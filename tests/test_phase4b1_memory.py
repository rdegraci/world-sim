"""Phase 4b1: optional bounded memory — privacy, caps, no canon smuggling."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.authority import WorldAuthority
from world_sim.config import (
    ConfigError,
    MemorySettings,
    parse_memory_settings,
)
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import COLLECTION_ROOM, ChromaManager
from world_sim.lore.seed import (
    ensure_player_starting_room,
    seed_starter_world,
)
from world_sim.orchestrator.context_builder import ContextBuilder
from world_sim.auth.password_utils import hash_password
from world_sim.tools.definitions import play_tool_schemas
from world_sim.tools.implementations import PlayTools
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def memory_runtime(tmp_path: Path) -> tuple[UserStore, WorldAuthority, ChromaManager]:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    users = UserStore(db.connection)
    store = WorldStore(db.connection)
    authority = WorldAuthority(
        store,
        memory=MemorySettings(
            enabled=True,
            max_per_subject=3,
            max_summary_chars=80,
            ttl_days=0,
        ),
    )
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(store, lore)
    return users, authority, lore


def _pc(users: UserStore, authority: WorldAuthority, name: str) -> int:
    user = users.create_player_user(name, hash_password("secret"))
    player = users.require_player_character_for_user(user.id)
    ensure_player_starting_room(authority.store, player.id)
    return player.id


def test_memory_default_off_empty_safe(tmp_path: Path) -> None:
    settings = parse_memory_settings({})
    assert settings.enabled is False
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    store = WorldStore(db.connection)
    authority = WorldAuthority(store)  # default memory off
    with pytest.raises(ValueError, match="off"):
        authority.remember(
            actor_player_character_id=1,
            summary="should not store",
        )
    assert authority.list_visible_memories(1) == []
    assert authority.format_visible_memories(1) == ""


def test_parse_memory_settings_bounds() -> None:
    on = parse_memory_settings(
        {
            "memory": {
                "enabled": True,
                "max_per_subject": 5,
                "max_summary_chars": 40,
                "ttl_days": 7,
            }
        }
    )
    assert on.enabled is True
    assert on.max_per_subject == 5
    assert on.max_summary_chars == 40
    assert on.ttl_days == 7
    with pytest.raises(ConfigError):
        parse_memory_settings({"memory": {"max_per_subject": 0}})


def test_play_tools_schemas_gated() -> None:
    base = play_tool_schemas(memory_enabled=False)
    with_mem = play_tool_schemas(memory_enabled=True)
    names = {t["function"]["name"] for t in base}
    assert "record_memory" not in names
    mem_names = {t["function"]["name"] for t in with_mem}
    assert "record_memory" in mem_names
    assert "forget_memory" in mem_names


def test_bounded_count_and_length(
    memory_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, _ = memory_runtime
    pc = _pc(users, authority, "alice")
    with pytest.raises(ValueError, match="at most"):
        authority.remember(actor_player_character_id=pc, summary="x" * 200)
    for i in range(5):
        authority.remember(
            actor_player_character_id=pc,
            summary=f"fact number {i}",
        )
    visible = authority.list_visible_memories(pc, limit=20)
    assert len(visible) == 3
    summaries = {m.summary for m in visible}
    assert "fact number 4" in summaries
    assert "fact number 0" not in summaries
    assert "fact number 1" not in summaries


def test_privacy_no_cross_player_memory(
    memory_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, lore = memory_runtime
    alice = _pc(users, authority, "alice")
    bob = _pc(users, authority, "bob")
    secret = authority.remember(
        actor_player_character_id=alice,
        summary="Alice hid a letter under the stairs",
    )
    bob_view = authority.list_visible_memories(bob)
    assert all(m.id != secret.id for m in bob_view)
    assert all("letter under the stairs" not in m.summary for m in bob_view)

    ctx_bob = ContextBuilder(authority.store, lore, authority=authority).build(bob)
    assert "letter under the stairs" not in ctx_bob.text
    ctx_alice = ContextBuilder(authority.store, lore, authority=authority).build(alice)
    assert "letter under the stairs" in ctx_alice.text

    with pytest.raises(ValueError, match="not yours"):
        authority.forget_memory(secret.id, actor_player_character_id=bob)


def test_memory_cannot_smuggle_canon_edits(
    memory_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, lore = memory_runtime
    pc = _pc(users, authority, "alice")
    foyer = authority.get_room("foyer")
    assert foyer is not None
    before = lore.get_lore(COLLECTION_ROOM, foyer.lore_key)
    assert before
    authority.remember(
        actor_player_character_id=pc,
        summary="The foyer is actually a spaceship hangar",
        about_kind="room",
        about_id="foyer",
        lore_key=foyer.lore_key,
    )
    after = lore.get_lore(COLLECTION_ROOM, foyer.lore_key)
    assert after == before
    # No scene-public runtime event for private memory.
    events = authority.list_runtime_events(limit=20)
    payloads = " ".join(p for _, _, p, _ in events)
    assert "spaceship hangar" not in payloads


def test_npc_memory_only_visible_to_about_player(
    memory_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, _ = memory_runtime
    alice = _pc(users, authority, "alice")
    bob = _pc(users, authority, "bob")
    mem = authority.remember(
        actor_player_character_id=alice,
        summary="Mrs Hale noticed Alice fidget with the key",
        subject_kind="npc",
        subject_id="mrs_hale",
    )
    alice_chat = authority.list_visible_memories(alice, npc_id="mrs_hale")
    bob_chat = authority.list_visible_memories(bob, npc_id="mrs_hale")
    assert any(m.id == mem.id for m in alice_chat)
    assert all(m.id != mem.id for m in bob_chat)
    # Without npc_id, play context still hides NPC-about memories from others
    # and does not include NPC memories in generic play (only own PC rows).
    alice_play = authority.list_visible_memories(alice)
    assert all(m.subject_kind == "player_character" for m in alice_play)


def test_record_memory_tool(
    memory_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, lore = memory_runtime
    pc = _pc(users, authority, "alice")
    tools = PlayTools(authority, lore, player_character_id=pc)
    result = tools.record_memory({"summary": "The brass key felt warm"})
    assert result.ok
    assert authority.list_visible_memories(pc)
    mid = result.data["memory_id"]
    forgotten = tools.forget_memory({"memory_id": mid})
    assert forgotten.ok
    assert authority.list_visible_memories(pc) == []


def test_memory_tools_refuse_when_disabled(tmp_path: Path) -> None:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    store = WorldStore(db.connection)
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(store, lore)
    authority = WorldAuthority(store, memory=MemorySettings(enabled=False))
    users = UserStore(db.connection)
    pc = _pc(users, authority, "alice")
    tools = PlayTools(authority, lore, player_character_id=pc)
    result = tools.record_memory({"summary": "nope"})
    assert not result.ok
