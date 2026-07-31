"""Phase 4a: contested arbitration, chat leases, transcript privacy."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from world_sim.authority import MutationConflict, WorldAuthority
from world_sim.config import AppPaths, Settings, WorldExpansionSettings
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
from world_sim.orchestrator.player_chat import PlayerChatOrchestrator
from world_sim.auth.password_utils import hash_password
from world_sim.server.app import WorldRuntime, create_app
from world_sim.server.hub import SessionHub
from world_sim.tools.implementations import PlayTools
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def authority_runtime(tmp_path: Path) -> tuple[UserStore, WorldAuthority, ChromaManager]:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    users = UserStore(db.connection)
    store = WorldStore(db.connection)
    authority = WorldAuthority(store)
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(store, lore)
    return users, authority, lore


def _auth(users: UserStore, authority: WorldAuthority, name: str) -> AuthContext:
    user = users.create_player_user(name, hash_password("secret"))
    player = users.require_player_character_for_user(user.id)
    ensure_player_starting_room(authority.store, player.id)
    session = users.create_session(user.id, player.id)
    return AuthContext(user=user, player_character=player, session=session)


def test_contested_frontier_realize_serial(
    authority_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    """Two concurrent stub realizes — one durable room, no SQLite race outside the gate."""
    from world_sim.lore.chroma_manager import COLLECTION_ROOM

    users, authority, lore = authority_runtime
    alice = _auth(users, authority, "alice")
    bob = _auth(users, authority, "bob")
    lore.upsert_lore(
        COLLECTION_ROOM,
        "room:garden",
        "A walled kitchen garden of damp earth and clipped rosemary.",
    )
    authority.upsert_frontier_stub(
        stub_id="stub_hallway_west_garden",
        from_room_id="hallway",
        direction="west",
        target_room_id="garden",
        target_name="Kitchen Garden",
        lore_key="room:garden",
        return_direction="east",
    )
    stub = authority.get_frontier_stub("stub_hallway_west_garden")
    assert stub is not None
    settings = WorldExpansionSettings(dynamic_expansion=True)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def attempt(label: str, pc_id: int) -> None:
        barrier.wait()
        try:
            done = authority.realize_frontier_stub(
                lore,
                stub,
                settings=settings,
                actor_player_character_id=pc_id,
            )
            results[label] = ("ok", done.status, done.target_room_id)
        except MutationConflict as exc:
            results[label] = ("conflict", exc.code)
        except Exception as exc:  # noqa: BLE001
            results[label] = ("error", str(exc))

    t1 = threading.Thread(target=attempt, args=("alice", alice.player_character.id))
    t2 = threading.Thread(target=attempt, args=("bob", bob.player_character.id))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert all(v[0] in {"ok", "conflict"} for v in results.values())
    assert any(v[0] == "ok" for v in results.values())
    garden = authority.get_room("garden")
    assert garden is not None
    assert garden.lore_key == "room:garden"
    refreshed = authority.get_frontier_stub("stub_hallway_west_garden")
    assert refreshed is not None and refreshed.status == "realized"
    assert authority.list_exits("hallway").get("west") == "garden"
    events = [
        e for e in authority.list_runtime_events(event_type="room_realized", limit=20)
    ]
    assert len(events) >= 1


def test_contested_take_one_wins_one_fails(
    authority_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, lore = authority_runtime
    alice = _auth(users, authority, "alice")
    bob = _auth(users, authority, "bob")
    # Both in foyer with the brass key.
    items = authority.list_items_in_room("foyer")
    key = next(i for i in items if i.name and "key" in i.name.lower())

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def attempt(label: str, pc_id: int) -> None:
        barrier.wait()
        try:
            taken = authority.take_item_from_room(pc_id, key.id)
            results[label] = ("ok", taken.id)
        except MutationConflict as exc:
            results[label] = ("conflict", exc.code)
        except Exception as exc:  # noqa: BLE001
            results[label] = ("error", str(exc))

    t1 = threading.Thread(target=attempt, args=("alice", alice.player_character.id))
    t2 = threading.Thread(target=attempt, args=("bob", bob.player_character.id))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    outcomes = list(results.values())
    assert any(o[0] == "ok" for o in outcomes)
    assert any(o[0] == "conflict" and o[1] in {"item_gone", "item_claimed"} for o in outcomes)
    # Exactly one holder.
    holders = authority.list_player_items(alice.player_character.id) + authority.list_player_items(
        bob.player_character.id
    )
    assert sum(1 for i in holders if i.id == key.id) == 1
    assert authority.list_items_in_room("foyer") == []


def test_play_tools_surface_structured_refusal(
    authority_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, lore = authority_runtime
    alice = _auth(users, authority, "alice")
    bob = _auth(users, authority, "bob")
    items = authority.list_items_in_room("foyer")
    key = next(i for i in items if i.name and "key" in i.name.lower())
    authority.take_item_from_room(alice.player_character.id, key.id)

    tools = PlayTools(authority, lore, player_character_id=bob.player_character.id)
    result = tools.take_item({"item_instance_id": key.id})
    assert result.ok is False
    assert result.data is not None
    assert result.data["refusal"]["code"] == "item_gone"


def test_player_chat_lease_exclusive(
    authority_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, lore = authority_runtime
    alice = _auth(users, authority, "alice")
    bob = _auth(users, authority, "bob")
    # Move both to study where Mrs. Hale is.
    authority.set_player_room(alice.player_character.id, "study")
    authority.set_player_room(bob.player_character.id, "study")

    chat_a = PlayerChatOrchestrator(
        world=authority,
        lore=lore,
        llm=FakeAdapter(),
        user_store=users,
        auth=alice,
    )
    chat_b = PlayerChatOrchestrator(
        world=authority,
        lore=lore,
        llm=FakeAdapter(),
        user_store=users,
        auth=bob,
    )
    entered_a = chat_a.try_enter("talk to Mrs. Hale")
    assert entered_a is not None and entered_a.ok
    entered_b = chat_b.try_enter("talk to Mrs. Hale")
    assert entered_b is not None and entered_b.ok is False
    assert "engaged" in entered_b.message.lower() or "conversation" in entered_b.message.lower()

    busy = authority.list_busy_npcs_in_room("study")
    assert any(n["npc_id"] == DEFAULT_CHAT_NPC_ID for n in busy)

    chat_a.end(reason="player")
    entered_b2 = chat_b.try_enter("talk to Mrs. Hale")
    assert entered_b2 is not None and entered_b2.ok


def test_transcripts_private_per_session(
    authority_runtime: tuple[UserStore, WorldAuthority, ChromaManager],
) -> None:
    users, authority, lore = authority_runtime
    alice = _auth(users, authority, "alice")
    bob = _auth(users, authority, "bob")
    users.append_transcript(alice.session.id, "user", "alice secret line")
    users.append_transcript(bob.session.id, "user", "bob secret line")

    alice_lines = [e.content for e in users.list_transcripts(alice.session.id)]
    bob_lines = [e.content for e in users.list_transcripts(bob.session.id)]
    assert "alice secret line" in alice_lines
    assert "bob secret line" not in alice_lines
    assert "bob secret line" in bob_lines
    assert "alice secret line" not in bob_lines


def test_web_contested_take_and_chat_lease(tmp_path: Path) -> None:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    users = UserStore(db.connection)
    store = WorldStore(db.connection)
    authority = WorldAuthority(store)
    lore = ChromaManager(tmp_path / "chroma")
    seed_starter_world(store, lore)
    settings = Settings(
        paths=AppPaths(
            config_dir=tmp_path,
            data_dir=tmp_path,
            env_path=tmp_path / ".env",
            config_path=tmp_path / "config.yaml",
            sqlite_path=tmp_path / "world.sqlite3",
            chroma_dir=tmp_path / "chroma",
        ),
        provider="fake",
        log_level="INFO",
        grok_api_key="",
        openai_api_key=None,
        anthropic_api_key=None,
        admin_password="admin-secret",
        raw_config={},
        world=WorldExpansionSettings(),
    )
    hub = SessionHub(authority=authority)
    runtime = WorldRuntime(
        settings=settings,
        user_store=users,
        authority=authority,
        lore=lore,
        llm=FakeAdapter(),
        hub=hub,
    )
    app = create_app(runtime)

    def login(client: TestClient, name: str) -> dict:
        res = client.post(
            "/api/login",
            json={"username": name, "password": "secret", "allow_signup": True},
        )
        assert res.status_code == 200
        return res.json()

    with TestClient(app) as client:
        a = login(client, "alice")
        b = login(client, "bob")
        # Place both in study for chat contest.
        authority.set_player_room(a["player_character_id"], "study")
        authority.set_player_room(b["player_character_id"], "study")

        with client.websocket_connect(f"/ws?token={a['token']}") as ws_a:
            while True:
                msg = ws_a.receive_json()
                if msg.get("type") == "hello":
                    break
            with client.websocket_connect(f"/ws?token={b['token']}") as ws_b:
                while True:
                    msg = ws_b.receive_json()
                    if msg.get("type") == "hello":
                        break

                ws_a.send_json({"type": "action", "text": "talk to Mrs. Hale"})
                reply_a = None
                for _ in range(12):
                    msg = ws_a.receive_json()
                    if msg.get("type") == "reply":
                        reply_a = msg
                        break
                assert reply_a is not None and reply_a.get("ok") is True

                ws_b.send_json({"type": "action", "text": "talk to Mrs. Hale"})
                reply_b = None
                for _ in range(12):
                    msg = ws_b.receive_json()
                    if msg.get("type") == "reply":
                        reply_b = msg
                        break
                assert reply_b is not None
                assert reply_b.get("ok") is False
                assert "engaged" in reply_b["reply"].lower() or "conversation" in reply_b["reply"].lower()

                ws_a.send_json({"type": "action", "text": "end_chat"})
                for _ in range(12):
                    msg = ws_a.receive_json()
                    if msg.get("type") == "reply":
                        break

                # Contested take while both still attached (same WorldAuthority).
                authority.set_player_room(a["player_character_id"], "foyer")
                authority.set_player_room(b["player_character_id"], "foyer")
                hub.update_room(
                    next(c.connection_id for c in hub.connections.values() if c.auth.player_character.id == a["player_character_id"]),
                    "foyer",
                )
                hub.update_room(
                    next(c.connection_id for c in hub.connections.values() if c.auth.player_character.id == b["player_character_id"]),
                    "foyer",
                )
                runtime._plays.clear()  # noqa: SLF001

                ws_a.send_json({"type": "action", "text": "take brass key"})
                reply_take_a = None
                for _ in range(20):
                    msg = ws_a.receive_json()
                    if msg.get("type") == "reply" and "take" in (msg.get("reply") or "").lower():
                        reply_take_a = msg
                        break
                    if msg.get("type") == "reply" and msg.get("tool_names") == ["take_item"]:
                        reply_take_a = msg
                        break
                ws_b.send_json({"type": "action", "text": "take brass key"})
                reply_take_b = None
                for _ in range(20):
                    msg = ws_b.receive_json()
                    if msg.get("type") != "reply":
                        continue
                    reply_take_b = msg
                    break
                assert reply_take_a is not None and reply_take_b is not None
                # One success, one deterministic runtime refusal (not LLM inventing a win).
                oks = [bool(reply_take_a.get("ok")), bool(reply_take_b.get("ok"))]
                assert True in oks and False in oks
                loser = reply_take_a if not reply_take_a.get("ok") else reply_take_b
                low = loser["reply"].lower()
                assert "not among" in low or "not here" in low or "first" in low or "present" in low
