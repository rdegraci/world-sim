"""Tests for SQLite schema and identity persistence (Slice 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlite3

from world_sim.auth.password_utils import hash_password
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import AuthStoreError, UserStore


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    db = SqliteManager(tmp_path / "world_sim.sqlite3")
    db.initialize_schema()
    return UserStore(db.connection)


def test_schema_creates_required_tables(tmp_path: Path) -> None:
    db = SqliteManager(tmp_path / "world_sim.sqlite3")
    db.initialize_schema()
    rows = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {row["name"] for row in rows}
    assert {
        "users",
        "player_characters",
        "player_inventory",
        "item_instances",
        "sessions",
        "transcripts",
    }.issubset(names)


def test_create_player_enforces_one_to_one(store: UserStore) -> None:
    user = store.create_player_user("rodney", hash_password("secret"))
    player = store.require_player_character_for_user(user.id)
    assert player.user_id == user.id
    assert player.name == "rodney"

    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            "INSERT INTO player_characters (user_id, name) VALUES (?, ?)",
            (user.id, "duplicate"),
        )
        store.connection.commit()
    store.connection.rollback()


def test_session_and_transcript_persist(store: UserStore) -> None:
    user = store.create_player_user("alice", hash_password("pw"))
    player = store.require_player_character_for_user(user.id)
    session = store.create_session(user.id, player.id)

    first = store.append_transcript(session.id, "user", "hello")
    second = store.append_transcript(session.id, "system", "welcome")
    entries = store.list_transcripts(session.id)

    assert [entry.sequence_no for entry in entries] == [1, 2]
    assert entries[0].content == "hello"
    assert entries[1].speaker == "system"
    assert first.id != second.id

    ended = store.end_session(session.id)
    assert ended.status == "ended"
    assert ended.ended_at is not None


def test_inventory_tracks_item_instances_separately_from_lore(
    store: UserStore,
) -> None:
    user = store.create_player_user("bob", hash_password("pw"))
    player = store.require_player_character_for_user(user.id)
    item = store.create_item_instance(definition_key="lore:item:lantern")
    store.add_item_to_player_inventory(player.id, item.id)

    inventory = store.list_player_inventory(player.id)
    assert len(inventory) == 1
    assert inventory[0].id == item.id
    assert inventory[0].definition_key == "lore:item:lantern"
    assert inventory[0].location_kind == "player_character"
    assert inventory[0].location_id == str(player.id)


def test_admin_user_has_null_password_hash(store: UserStore) -> None:
    admin = store.ensure_admin_user()
    assert admin.role == "admin"
    assert admin.password_hash is None
    player = store.require_player_character_for_user(admin.id)
    assert player.user_id == admin.id

    again = store.ensure_admin_user()
    assert again.id == admin.id


def test_duplicate_username_rejected(store: UserStore) -> None:
    store.create_player_user("casey", hash_password("pw"))
    with pytest.raises(AuthStoreError):
        store.create_player_user("Casey", hash_password("other"))
