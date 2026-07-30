"""Phase 2b: richer edit_mode drafts, approval, and invalidation."""

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
    COLLECTION_ITEM,
    COLLECTION_NPC,
    COLLECTION_ROOM,
    ChromaManager,
)
from world_sim.lore.seed import ensure_player_starting_room, seed_starter_world
from world_sim.models import AuthContext
from world_sim.orchestrator.edit import EditAccessError, EditOrchestrator
from world_sim.orchestrator.presentation import present_item, present_npc, present_room
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


def test_create_room_lore_requires_approve_and_invalidates(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, drafts, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id
    first = present_room(world, lore, player_character_id=pc, room_id="foyer")
    assert "[presentation=full]" in first
    seen, recap = world.get_room_presentation(pc, "foyer")
    assert seen is True
    assert recap is not None

    edit = _edit(runtime, auth)
    created = edit.handle("create_room_lore foyer Mention damp coats by the door")
    assert created.ok
    assert "NOT canonical" in created.message
    draft = drafts.list_drafts(status="pending")[0]
    assert draft.collection_name == COLLECTION_ROOM
    assert draft.proposed_key == "room:foyer"
    # Draft must not replace canon yet
    current = lore.get_lore(COLLECTION_ROOM, "room:foyer")
    assert current is not None
    assert "damp coats" not in current.lower() or "Draft" in created.message

    before_approve = lore.get_lore(COLLECTION_ROOM, "room:foyer")
    approved = edit.handle(f"approve_draft {draft.id}")
    assert approved.ok
    assert "invalidated" in approved.message.lower()
    after = lore.get_lore(COLLECTION_ROOM, "room:foyer")
    assert after is not None
    assert after != before_approve or "damp coats" in after.lower()

    seen_after, recap_after = world.get_room_presentation(pc, "foyer")
    assert seen_after is False
    assert recap_after is None
    again = present_room(world, lore, player_character_id=pc, room_id="foyer")
    assert "[presentation=full]" in again


def test_create_item_lore_draft_gate(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, drafts, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id
    item = world.list_items_in_room("foyer")[0]
    present_item(
        world,
        lore,
        player_character_id=pc,
        item_instance_id=item.id,
    )
    seen, _recap = world.get_item_presentation(pc, item.id)
    assert seen is True

    edit = _edit(runtime, auth)
    created = edit.handle("create_item_lore brass_key Emphasize a scratched numeral")
    assert created.ok
    draft = drafts.list_drafts(status="pending")[0]
    assert draft.proposed_key == "item:brass_key"
    assert lore.get_lore(COLLECTION_ITEM, "item:brass_key") is not None

    approved = edit.handle(f"approve_draft {draft.id}")
    assert approved.ok
    seen_after, recap_after = world.get_item_presentation(pc, item.id)
    assert seen_after is False
    assert recap_after is None
    text = lore.get_lore(COLLECTION_ITEM, "item:brass_key")
    assert text is not None
    assert "numeral" in text.lower() or "brass_key" in text.lower()


def test_create_npc_approve_creates_record(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, drafts, lore = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    created = edit.handle("create_npc A gardener who tends the courtyard pots")
    assert created.ok
    draft = drafts.list_drafts(status="pending")[0]
    assert draft.collection_name == COLLECTION_NPC
    assert world.get_npc(draft.proposed_key.split(":")[1]) is None

    approved = edit.handle(f"approve_draft {draft.id}")
    assert approved.ok
    npc_id = draft.proposed_key.split(":")[1]
    npc = world.get_npc(npc_id)
    assert npc is not None
    assert draft.proposed_key in npc.npc_lore
    assert lore.get_lore(COLLECTION_NPC, draft.proposed_key) is not None


def test_list_filters_and_entity_lists(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, _ = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    rooms = edit.handle("list_rooms search=foyer")
    assert "foyer" in rooms.message
    room_lore = edit.handle("list_room_lore room_id=foyer")
    assert "room:foyer" in room_lore.message
    items = edit.handle("list_items search=brass")
    assert "brass_key" in items.message
    item_lore = edit.handle("list_item_lore item_id=brass_key")
    assert "item:brass_key" in item_lore.message


def test_delete_room_lore_refuses_when_linked(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, _ = runtime
    auth = _admin_auth(user_store, world)
    edit = _edit(runtime, auth)
    result = edit.handle("delete_room_lore room:foyer")
    assert not result.ok
    assert "Refusing" in result.message


def test_runtime_move_still_does_not_invalidate_after_phase2b(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id
    present_room(world, lore, player_character_id=pc, room_id="foyer")
    seen_before, recap_before = world.get_room_presentation(pc, "foyer")
    world.move_player(pc, "north")
    seen_after, recap_after = world.get_room_presentation(pc, "foyer")
    assert seen_after is True
    assert recap_after == recap_before


def test_maintenance_path_list_draft_approve_full_again(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    """list → create draft → approve → play sees full description again."""
    user_store, world, drafts, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id
    edit = _edit(runtime, auth)

    listed = edit.handle("list_room_lore search=study")
    assert "room:study" in listed.message
    present_room(world, lore, player_character_id=pc, room_id="study")
    present_room(world, lore, player_character_id=pc, room_id="study")
    seen, _ = world.get_room_presentation(pc, "study")
    assert seen is True

    created = edit.handle("create_room_lore study Soften the lamp light wording")
    assert created.ok
    draft = drafts.list_drafts(status="pending")[0]
    viewed = edit.handle(f"view_draft {draft.id}")
    assert viewed.ok
    approved = edit.handle(f"approve_draft {draft.id}")
    assert approved.ok

    seen_after, recap_after = world.get_room_presentation(pc, "study")
    assert seen_after is False
    assert recap_after is None
    shown = present_room(world, lore, player_character_id=pc, room_id="study")
    assert "[presentation=full]" in shown


def test_non_admin_still_blocked(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, drafts, lore = runtime
    user = user_store.create_player_user("pat", hash_password("secret"))
    player = user_store.require_player_character_for_user(user.id)
    ensure_player_starting_room(world, player.id)
    session = user_store.create_session(user.id, player.id)
    auth = AuthContext(user=user, player_character=player, session=session)
    edit = EditOrchestrator(
        world=world,
        lore=lore,
        drafts=drafts,
        llm=FakeAdapter(),
        auth=auth,
    )
    with pytest.raises(EditAccessError):
        edit.handle("create_room_lore foyer anything")


def test_npc_canon_edit_still_invalidates(
    runtime: tuple[UserStore, WorldStore, DraftStore, ChromaManager],
) -> None:
    user_store, world, _, lore = runtime
    auth = _admin_auth(user_store, world)
    pc = auth.player_character.id
    present_npc(world, lore, player_character_id=pc, npc_id="mrs_hale")
    edit = _edit(runtime, auth)
    result = edit.handle(
        "add_npc_lore mrs_hale | Mrs. Hale adjusts a navy shawl in the study light."
    )
    assert result.ok
    seen, recap = world.get_npc_presentation(pc, "mrs_hale")
    assert seen is False
    assert recap is None
