"""Slice 4 tests: admin edit_mode, drafts, and presentation invalidation."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.auth.password_utils import hash_password
from world_sim.db.draft_store import DraftStore
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.lore.chroma_manager import (
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)
from world_sim.lore.seed import ensure_player_starting_room, seed_starter_world
from world_sim.models import AuthContext
from world_sim.orchestrator.edit import EditAccessError, EditOrchestrator
from world_sim.orchestrator.presentation import present_room
from world_sim.server.session_server import run_session
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


def _admin_auth(
    user_store: UserStore,
    world: WorldStore,
) -> AuthContext:
    user = user_store.ensure_admin_user()
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def _player_auth(
    user_store: UserStore,
    world: WorldStore,
    username: str = "morgan",
) -> AuthContext:
    user = user_store.create_player_user(username, hash_password("secret"))
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    session = user_store.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def _edit(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
    auth: AuthContext,
) -> EditOrchestrator:
    _user_store, world, drafts, lore = runtime
    return EditOrchestrator(
        world=world,
        lore=lore,
        drafts=drafts,
        llm=FakeAdapter(),
        auth=auth,
    )


def test_non_admin_cannot_use_edit_commands(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, _ = runtime
    auth = _player_auth(user_store, world)
    edit = _edit(runtime, auth)
    with pytest.raises(EditAccessError):
        edit.handle("list_system_lore")


def test_session_blocks_mode_edit_for_non_admin(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, drafts, lore = runtime
    auth = _player_auth(user_store, world)
    edit = EditOrchestrator(
        world=world,
        lore=lore,
        drafts=drafts,
        llm=FakeAdapter(),
        auth=auth,
    )
    outputs: list[str] = []
    inputs = iter(["mode edit", "quit"])
    code = run_session(
        auth=auth,
        store=user_store,
        edit=edit,
        input_fn=lambda _: next(inputs),
        output_fn=outputs.append,
    )
    assert code == 0
    assert any("admin-only" in line for line in outputs)


def test_add_list_view_system_lore(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)

    added = edit.handle(
        "add_system_lore system:bell | The manor bell rings only at dusk."
    )
    assert added.ok
    listed = edit.handle("list_system_lore search=bell")
    assert "system:bell" in listed.message
    viewed = edit.handle("view_system_lore system:bell")
    assert "rings only at dusk" in viewed.message
    assert lore.get_lore(COLLECTION_SYSTEM, "system:bell") is not None


def test_create_requires_approve_before_canon(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, drafts, lore = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)

    created = edit.handle("create_system_lore A hidden cellar beneath the foyer")
    assert created.ok
    assert "NOT canonical" in created.message
    pending = drafts.list_drafts(status="pending")
    assert len(pending) == 1
    draft = pending[0]
    assert lore.get_lore(COLLECTION_SYSTEM, draft.proposed_key) is None

    approved = edit.handle(f"approve_draft {draft.id}")
    assert approved.ok
    assert lore.get_lore(COLLECTION_SYSTEM, draft.proposed_key) is not None
    assert drafts.get_draft(draft.id).status == "approved"  # type: ignore[union-attr]


def test_reject_draft_does_not_write_canon(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, drafts, lore = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    created = edit.handle("create_system_lore Something temporary")
    draft = drafts.list_drafts(status="pending")[0]
    rejected = edit.handle(f"reject_draft {draft.id}")
    assert rejected.ok
    assert lore.get_lore(COLLECTION_SYSTEM, draft.proposed_key) is None
    assert drafts.get_draft(draft.id).status == "rejected"  # type: ignore[union-attr]


def test_room_lore_edit_invalidates_presentation(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id
    first = present_room(world, lore, player_character_id=pc, room_id="foyer")
    assert "[presentation=full]" in first
    seen, recap = world.get_room_presentation(pc, "foyer")
    assert seen is True
    assert recap is not None

    edit = _edit(runtime, auth)
    result = edit.handle(
        "add_room_lore foyer | The foyer now smells faintly of rain-soaked coats."
    )
    assert result.ok
    assert "invalidated" in result.message.lower()

    seen_after, recap_after = world.get_room_presentation(pc, "foyer")
    assert seen_after is False
    assert recap_after is None
    updated = lore.get_lore(COLLECTION_ROOM, "room:foyer")
    assert updated is not None
    assert "rain-soaked coats" in updated

    again = present_room(world, lore, player_character_id=pc, room_id="foyer")
    assert "[presentation=full]" in again
    assert "rain-soaked coats" in again


def test_edit_lore_aliases_match_add_upsert(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)

    system = edit.handle(
        "edit_system_lore system:alias_bell | The alias bell rings once."
    )
    assert system.ok
    assert lore.get_lore(COLLECTION_SYSTEM, "system:alias_bell") is not None

    room = edit.handle(
        "edit_room_lore foyer | The foyer smells of wet wool from the alias path."
    )
    assert room.ok
    foyer = lore.get_lore(COLLECTION_ROOM, "room:foyer")
    assert foyer is not None
    assert "wet wool" in foyer

    item = edit.handle(
        "edit_item_lore brass_key | A brass key rewritten via edit_item_lore."
    )
    assert item.ok

    npc = edit.handle(
        "edit_npc_lore mrs_hale | Mrs. Hale watches the door via the lore alias."
    )
    assert npc.ok

    # edit_npc remains rename-only and must not be swallowed by edit_npc_lore.
    renamed = edit.handle("edit_npc mrs_hale | name=Mrs. Hale Alias")
    assert renamed.ok
    assert world.get_npc("mrs_hale").name == "Mrs. Hale Alias"  # type: ignore[union-attr]


def test_item_lore_edit_keeps_instances_as_runtime(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    before = world.list_items_in_room("foyer")
    assert before
    item = before[0]

    edit = _edit(runtime, auth)
    result = edit.handle(
        "add_item_lore brass_key | A colder brass key with a scratched numeral 7."
    )
    assert result.ok
    after = world.get_item_instance(item.id)
    assert after is not None
    assert after.location_kind == "room"
    assert after.location_id == "foyer"
    text = lore.get_lore("item_lore", "item:brass_key")
    assert text is not None
    assert "numeral 7" in text


def test_list_room_and_item_lore(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, _ = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    rooms = edit.handle("list_room_lore")
    assert "room:foyer" in rooms.message
    items = edit.handle("list_item_lore search=journal")
    assert "item:worn_journal" in items.message


def test_edit_help_per_command_includes_examples(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, _ = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    result = edit.handle("help add_npc")
    assert result.ok
    assert "Examples:" in result.message
    assert "add_npc jane | Jane | npc:jane:description --in study" in result.message


def test_edit_help_unknown_command(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, _ = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    result = edit.handle("help frobnicate")
    assert not result.ok
    assert "Unknown edit command" in result.message


def test_edit_help_alias_resolves(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, _ = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    result = edit.handle("help edit_npc_lore")
    assert result.ok
    assert "alias of add_npc_lore" in result.message
    assert "Examples:" in result.message


def test_edit_help_topic_drafts(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, _ = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    result = edit.handle("? approve_draft")
    assert result.ok
    assert "approve_draft 3" in result.message
