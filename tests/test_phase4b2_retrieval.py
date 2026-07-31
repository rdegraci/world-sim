"""Phase 4b2: optional semantic retrieval assist — augmentation only."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from world_sim.auth.password_utils import hash_password
from world_sim.authority import WorldAuthority
from world_sim.config import (
    ConfigError,
    RetrievalSettings,
    parse_retrieval_settings,
)
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import COLLECTION_ROOM, ChromaManager
from world_sim.lore.retrieval import RetrievalAssist
from world_sim.lore.seed import (
    SYSTEM_LORE_KEY,
    ensure_player_starting_room,
    seed_starter_world,
)
from world_sim.orchestrator.context_builder import ContextBuilder
from world_sim.builder.core import BuilderSession
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def lore_world(tmp_path: Path) -> tuple[WorldStore, ChromaManager]:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    store = WorldStore(db.connection)
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(store, lore)
    return store, lore


def test_retrieval_default_off() -> None:
    settings = parse_retrieval_settings({})
    assert settings.enabled is False
    assert settings.top_k == 5


def test_parse_retrieval_settings() -> None:
    on = parse_retrieval_settings(
        {
            "retrieval": {
                "enabled": True,
                "top_k": 3,
                "play_context": False,
                "builder_discover": True,
            }
        }
    )
    assert on.enabled is True
    assert on.top_k == 3
    assert on.play_context is False
    with pytest.raises(ConfigError):
        parse_retrieval_settings({"retrieval": {"top_k": 0}})


def test_disabled_assist_returns_empty(
    lore_world: tuple[WorldStore, ChromaManager],
) -> None:
    _, lore = lore_world
    assist = RetrievalAssist(lore, RetrievalSettings(enabled=False))
    assert assist.search("quiet manor") == []
    assert assist.format_assist_block("quiet manor") == ""
    assert "off" in assist.format_builder_discovery("quiet").lower()


def test_grounded_hits_via_get_lore(
    lore_world: tuple[WorldStore, ChromaManager],
) -> None:
    _, lore = lore_world
    assist = RetrievalAssist(
        lore,
        RetrievalSettings(enabled=True, top_k=5),
    )
    hits = assist.search("quiet foyer hallway", collections=(COLLECTION_ROOM,))
    assert hits
    for hit in hits:
        if hit.grounded:
            assert lore.get_lore(hit.collection, hit.lore_key) == hit.text
    grounded = assist.grounded_keys("quiet foyer", collections=(COLLECTION_ROOM,))
    for key in grounded:
        assert lore.get_lore(COLLECTION_ROOM, key) is not None


def test_ungrounded_hits_fail_closed(
    lore_world: tuple[WorldStore, ChromaManager],
) -> None:
    _, lore = lore_world
    assist = RetrievalAssist(lore, RetrievalSettings(enabled=True, top_k=3))

    def fake_query(
        collection_name: str,
        query_text: str,
        *,
        n_results: int = 5,
    ) -> list[tuple[str, str | None, float | None]]:
        del collection_name, query_text, n_results
        return [("room:does_not_exist_anywhere", "hallucinated text", 0.1)]

    with patch.object(lore, "query_similar", side_effect=fake_query):
        hits = assist.search("anything", collections=(COLLECTION_ROOM,))
        assert len(hits) == 1
        assert hits[0].grounded is False
        assert assist.grounded_keys("anything", collections=(COLLECTION_ROOM,)) == []
        block = assist.format_assist_block("anything")
        assert "Dropped" in block or "fail closed" in block.lower()
        assert "hallucinated text" not in block
        assert "[ASSIST grounded]" not in block


def test_play_context_authority_still_lore_keys(
    lore_world: tuple[WorldStore, ChromaManager],
    tmp_path: Path,
) -> None:
    store, lore = lore_world
    users = UserStore(store.connection)
    user = users.create_player_user("alice", hash_password("x"))
    player = users.require_player_character_for_user(user.id)
    ensure_player_starting_room(store, player.id)
    authority = WorldAuthority(store)
    assist = RetrievalAssist(
        lore,
        RetrievalSettings(enabled=True, top_k=5, play_context=True),
    )
    builder = ContextBuilder(
        store,
        lore,
        authority=authority,
        retrieval=assist,
    )
    ctx = builder.build(player.id, assist_query="look for secrets in the manor")
    foyer = store.get_room("foyer")
    assert foyer is not None
    # Authoritative path still names explicit lore_key from SQLite room row.
    assert f"Room lore_key={foyer.lore_key}" in ctx.text
    assert lore.get_lore(COLLECTION_ROOM, foyer.lore_key)
    assert SYSTEM_LORE_KEY in ctx.text
    assert "AUTHORITATIVE RUNTIME CONTEXT" in ctx.text
    # Assist is labeled non-authoritative when present.
    if "SEMANTIC RETRIEVAL ASSIST" in ctx.text:
        assert "non-authoritative" in ctx.text.lower()
        assert "suggestions only" in ctx.text.lower()

    # With retrieval off, assist block absent and context still grounded.
    off = ContextBuilder(
        store,
        lore,
        authority=authority,
        retrieval=RetrievalAssist(lore, RetrievalSettings(enabled=False)),
    )
    ctx_off = off.build(player.id, assist_query="look for secrets")
    assert "SEMANTIC RETRIEVAL ASSIST" not in ctx_off.text
    assert f"Room lore_key={foyer.lore_key}" in ctx_off.text


def test_builder_discover_and_propose_grounded_only(
    lore_world: tuple[WorldStore, ChromaManager],
    tmp_path: Path,
) -> None:
    store, lore = lore_world
    lore.upsert_lore(
        COLLECTION_ROOM,
        "room:cellar",
        "A damp cellar under the Quiet Manor, smelling of earth and old bottles.",
    )
    session = BuilderSession(
        store,
        lore,
        tmp_path,
        seed_starter=False,
        retrieval=RetrievalSettings(enabled=True, top_k=5),
    )
    text = session.discover_lore("damp cellar bottles")
    assert "grounded" in text.lower()
    assert "room:cellar" in text

    plan = session.propose_discovered("cellar under manor", kind="rooms")
    room_keys = [r.get("lore_key") for r in plan.rooms]
    for key in room_keys:
        assert key is None or lore.get_lore(COLLECTION_ROOM, str(key)) is not None


def test_builder_propose_discovered_refuses_when_off(
    lore_world: tuple[WorldStore, ChromaManager],
    tmp_path: Path,
) -> None:
    store, lore = lore_world
    session = BuilderSession(
        store,
        lore,
        tmp_path,
        seed_starter=False,
        retrieval=RetrievalSettings(enabled=False),
    )
    with pytest.raises(ValueError, match="off"):
        session.propose_discovered("foyer", kind="rooms")
