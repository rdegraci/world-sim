"""Phase 3b: multi-session WebSockets, presence, map fog, thin web APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from world_sim.authority import ITEM_TAKEN, WorldAuthority
from world_sim.config import AppPaths, Settings, WorldExpansionSettings
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.lore.seed import seed_starter_world
from world_sim.server.app import WorldRuntime, create_app
from world_sim.server.hub import SessionHub
from world_sim.server.map_view import build_map_view
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def runtime(tmp_path: Path) -> WorldRuntime:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    user_store = UserStore(db.connection)
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
    rt = WorldRuntime(
        settings=settings,
        user_store=user_store,
        authority=authority,
        lore=lore,
        llm=FakeAdapter(),
        hub=hub,
    )
    rt._db = db  # noqa: SLF001
    return rt


def _login(client: TestClient, username: str, password: str = "secret") -> dict:
    res = client.post(
        "/api/login",
        json={"username": username, "password": password, "allow_signup": True},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _recv_until(
    ws,
    msg_type: str,
    *,
    limit: int = 30,
    predicate=None,
) -> dict[str, Any]:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") != msg_type:
            continue
        if predicate is None or predicate(msg):
            return msg
    raise AssertionError(f"Did not receive type={msg_type!r}")


def test_two_sessions_attach_and_share_visible_take(runtime: WorldRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        a = _login(client, "alice")
        b = _login(client, "bob")
        assert a["player_character_id"] != b["player_character_id"]

        with client.websocket_connect(f"/ws?token={a['token']}") as ws_a:
            assert _recv_until(ws_a, "hello")["player_character_id"] == a["player_character_id"]

            with client.websocket_connect(f"/ws?token={b['token']}") as ws_b:
                assert _recv_until(ws_b, "hello")["type"] == "hello"

                # Hub presence is authoritative for live roster (WS may have stale broadcasts).
                roster = runtime.hub.presence_in_room("foyer")
                names = {p["display_name"] for p in roster}
                assert "alice" in names
                assert "bob" in names

                ws_a.send_json({"type": "get_presence"})
                presence = _recv_until(
                    ws_a,
                    "presence",
                    predicate=lambda m: len(m.get("roster") or []) >= 2,
                )
                assert {p["display_name"] for p in presence["roster"]} >= {"alice", "bob"}

                ws_a.send_json({"type": "action", "text": "take brass key"})
                _recv_until(ws_a, "reply")
                event = _recv_until(
                    ws_b,
                    "event",
                    predicate=lambda m: (m.get("event") or {}).get("event_type")
                    == ITEM_TAKEN,
                )
                assert event["event"]["payload"]["name"] == "brass key"


def test_no_cross_room_event_leak(runtime: WorldRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        a = _login(client, "alice")
        b = _login(client, "bob")
        runtime.authority.set_player_room(b["player_character_id"], "hallway")

        with client.websocket_connect(f"/ws?token={a['token']}") as ws_a:
            _recv_until(ws_a, "hello")
            with client.websocket_connect(f"/ws?token={b['token']}") as ws_b:
                _recv_until(ws_b, "hello")

                ws_a.send_json({"type": "action", "text": "take brass key"})
                _recv_until(ws_a, "reply")

                ws_b.send_json({"type": "ping"})
                assert _recv_until(ws_b, "pong")["type"] == "pong"

                ws_b.send_json({"type": "get_presence"})
                presence = _recv_until(ws_b, "presence")
                assert presence["room_id"] == "hallway"
                assert all(p["display_name"] != "alice" for p in presence["roster"])


def test_map_fog_and_you_are_here_after_move(runtime: WorldRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        a = _login(client, "mapper")
        pc = a["player_character_id"]
        with client.websocket_connect(f"/ws?token={a['token']}") as ws:
            hello = _recv_until(ws, "hello")
            nodes = {n["room_id"] for n in hello["map"]["nodes"]}
            assert "foyer" in nodes

            ws.send_json({"type": "move", "direction": "north"})
            reply = _recv_until(ws, "reply")
            assert reply.get("room_id") == "hallway"
            map_after = _recv_until(ws, "map")
            here = [n for n in map_after["map"]["nodes"] if n.get("you_are_here")]
            assert len(here) == 1
            assert here[0]["room_id"] == "hallway"

        view = build_map_view(
            runtime.authority,
            player_character_id=pc,
            lod="near",
            presence_by_room={},
        )
        ids = {n["room_id"] for n in view["nodes"]}
        assert "hallway" in ids
        assert "study" not in ids


def test_say_is_room_scoped(runtime: WorldRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        a = _login(client, "alice")
        b = _login(client, "bob")
        with client.websocket_connect(f"/ws?token={a['token']}") as ws_a:
            _recv_until(ws_a, "hello")
            with client.websocket_connect(f"/ws?token={b['token']}") as ws_b:
                _recv_until(ws_b, "hello")
                ws_a.send_json({"type": "say", "text": "Hello manor"})
                ack = _recv_until(ws_a, "say_ack")
                assert ack["type"] == "say_ack"
                event = _recv_until(ws_b, "event")
                assert event["event"]["event_type"] == "character_said"
                assert event["event"]["payload"]["text"] == "Hello manor"


def test_http_map_requires_auth(runtime: WorldRuntime) -> None:
    app = create_app(runtime)
    with TestClient(app) as client:
        assert client.get("/api/map").status_code == 401
        data = _login(client, "carto")
        res = client.get(
            "/api/map",
            headers={"Authorization": f"Bearer {data['token']}"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "nodes" in body
        assert body["fog"] is True
