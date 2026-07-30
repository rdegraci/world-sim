"""FastAPI multi-session server: auth, WebSockets, map, thin web static."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from world_sim.auth.api_auth import authenticate_credentials
from world_sim.auth.onboarding import AuthError
from world_sim.authority import WorldAuthority
from world_sim.config import Settings
from world_sim.db.user_store import UserStore
from world_sim.llm.base import LLMAdapter
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.lore.seed import ensure_player_starting_room
from world_sim.orchestrator.play import PlayOrchestrator
from world_sim.server.hub import SessionHub
from world_sim.server.map_view import build_map_view
from world_sim.tools.implementations import normalize_direction
from world_sim.utils.logger import get_logger

STATIC_DIR = Path(__file__).resolve().parent / "static"


class LoginRequest(BaseModel):
    username: str
    password: str
    allow_signup: bool = True


class LoginResponse(BaseModel):
    token: str
    session_id: int
    user_id: int
    username: str
    role: str
    player_character_id: int
    player_name: str
    room_id: str | None


class SayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ActionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MoveRequest(BaseModel):
    direction: str


class WorldRuntime:
    """Shared process state for the networked world."""

    def __init__(
        self,
        *,
        settings: Settings,
        user_store: UserStore,
        authority: WorldAuthority,
        lore: ChromaManager,
        llm: LLMAdapter,
        hub: SessionHub,
    ) -> None:
        self.settings = settings
        self.user_store = user_store
        self.authority = authority
        self.lore = lore
        self.llm = llm
        self.hub = hub
        self._plays: dict[int, PlayOrchestrator] = {}
        self._logger = get_logger("web")

    def play_for(self, auth) -> PlayOrchestrator:  # noqa: ANN001
        pc_id = auth.player_character.id
        existing = self._plays.get(pc_id)
        if existing is not None and existing.auth.session.id == auth.session.id:
            return existing
        play = PlayOrchestrator(
            world=self.authority,
            lore=self.lore,
            llm=self.llm,
            user_store=self.user_store,
            auth=auth,
            expansion=self.settings.world,
        )
        self._plays[pc_id] = play
        return play


def create_app(runtime: WorldRuntime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.hub.bind_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(title="World-Sim", version="0.3b", lifespan=lifespan)
    app.state.runtime = runtime
    hub = runtime.hub

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/login", response_model=LoginResponse)
    def login(body: LoginRequest) -> LoginResponse:
        try:
            auth = authenticate_credentials(
                runtime.user_store,
                username=body.username,
                password=body.password,
                admin_password=runtime.settings.admin_password,
                allow_signup=body.allow_signup,
            )
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        ensure_player_starting_room(
            runtime.authority.store,
            auth.player_character.id,
        )
        token = hub.issue_token(auth)
        room_id = runtime.authority.get_player_room_id(auth.player_character.id)
        return LoginResponse(
            token=token,
            session_id=auth.session.id,
            user_id=auth.user.id,
            username=auth.user.username,
            role=auth.user.role,
            player_character_id=auth.player_character.id,
            player_name=auth.player_character.name,
            room_id=room_id,
        )

    def _auth_from_header(authorization: str | None):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Bearer token required.")
        token = authorization.split(" ", 1)[1].strip()
        auth = hub.take_pending_auth(token)
        if auth is None:
            conn = hub.get_by_token(token)
            if conn is None:
                raise HTTPException(status_code=401, detail="Invalid token.")
            return conn.auth, token
        return auth, token

    @app.get("/api/me")
    def me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth, _token = _auth_from_header(authorization)
        room_id = runtime.authority.get_player_room_id(auth.player_character.id)
        return {
            "username": auth.user.username,
            "role": auth.user.role,
            "player_character_id": auth.player_character.id,
            "player_name": auth.player_character.name,
            "session_id": auth.session.id,
            "room_id": room_id,
        }

    @app.get("/api/presence")
    def presence(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        auth, _token = _auth_from_header(authorization)
        room_id = runtime.authority.get_player_room_id(auth.player_character.id)
        if room_id is None:
            return {"room_id": None, "roster": []}
        return {"room_id": room_id, "roster": hub.presence_in_room(room_id)}

    @app.get("/api/map")
    def map_endpoint(
        lod: str = "near",
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth, _token = _auth_from_header(authorization)
        return build_map_view(
            runtime.authority,
            player_character_id=auth.player_character.id,
            lod=lod,
            presence_by_room=hub.presence_by_room(),
        )

    @app.post("/api/say")
    def say(
        body: SayRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth, _token = _auth_from_header(authorization)
        room_id = runtime.authority.get_player_room_id(auth.player_character.id)
        if room_id is None:
            raise HTTPException(status_code=400, detail="Not placed in a room.")
        try:
            event = runtime.authority.say_public(
                player_character_id=auth.player_character.id,
                display_name=auth.player_character.name,
                room_id=room_id,
                text=body.text,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime.user_store.append_transcript(
            auth.session.id,
            "user",
            f"(say) {body.text}",
        )
        return {"ok": True, "event": event.to_dict()}

    @app.post("/api/action")
    def action(
        body: ActionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth, token = _auth_from_header(authorization)
        return _handle_play_line(runtime, hub, auth, token, body.text)

    @app.post("/api/move")
    def move(
        body: MoveRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        auth, token = _auth_from_header(authorization)
        direction = normalize_direction(body.direction) or body.direction
        return _handle_play_line(runtime, hub, auth, token, f"go {direction}")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        token = websocket.query_params.get("token", "").strip()
        if not token:
            await websocket.close(code=4401)
            return
        auth = hub.take_pending_auth(token)
        if auth is None:
            await websocket.send_json({"type": "error", "message": "Invalid token."})
            await websocket.close(code=4401)
            return

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def send(message: dict[str, Any]) -> None:
            await queue.put(message)

        room_id = runtime.authority.get_player_room_id(auth.player_character.id)
        try:
            conn = hub.attach(token=token, send=send, room_id=room_id)
        except ValueError as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=4401)
            return

        play = runtime.play_for(auth)
        opening = play.opening_presentation()
        await websocket.send_json(
            {
                "type": "hello",
                "player_character_id": auth.player_character.id,
                "player_name": auth.player_character.name,
                "room_id": room_id,
                "opening": opening,
                "presence": hub.presence_in_room(room_id) if room_id else [],
                "map": build_map_view(
                    runtime.authority,
                    player_character_id=auth.player_character.id,
                    lod="near",
                    presence_by_room=hub.presence_by_room(),
                ),
            }
        )
        await hub._broadcast_presence(room_id) if room_id else None

        async def writer() -> None:
            while True:
                message = await queue.get()
                await websocket.send_json(message)

        writer_task = asyncio.create_task(writer())
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"type": "error", "message": "Expected JSON message."}
                    )
                    continue
                msg_type = str(data.get("type", "")).strip().lower()
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
                if msg_type == "say":
                    text = str(data.get("text", ""))
                    room = runtime.authority.get_player_room_id(
                        auth.player_character.id
                    )
                    if not room:
                        await websocket.send_json(
                            {"type": "error", "message": "Not placed in a room."}
                        )
                        continue
                    try:
                        event = runtime.authority.say_public(
                            player_character_id=auth.player_character.id,
                            display_name=auth.player_character.name,
                            room_id=room,
                            text=text,
                        )
                    except ValueError as exc:
                        await websocket.send_json(
                            {"type": "error", "message": str(exc)}
                        )
                        continue
                    await websocket.send_json(
                        {
                            "type": "say_ack",
                            "event": event.to_dict(),
                        }
                    )
                    continue
                if msg_type == "get_presence":
                    room = runtime.authority.get_player_room_id(
                        auth.player_character.id
                    )
                    await websocket.send_json(
                        {
                            "type": "presence",
                            "room_id": room,
                            "roster": hub.presence_in_room(room) if room else [],
                        }
                    )
                    continue
                if msg_type == "get_map":
                    lod = str(data.get("lod", "near"))
                    await websocket.send_json(
                        {
                            "type": "map",
                            "map": build_map_view(
                                runtime.authority,
                                player_character_id=auth.player_character.id,
                                lod=lod,
                                presence_by_room=hub.presence_by_room(),
                            ),
                        }
                    )
                    continue
                if msg_type == "move":
                    direction = str(data.get("direction", ""))
                    line = f"go {direction}"
                elif msg_type == "action":
                    line = str(data.get("text", "")).strip()
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": (
                                "Unknown type. Use action, move, say, "
                                "get_map, get_presence, ping."
                            ),
                        }
                    )
                    continue

                result = await asyncio.to_thread(
                    _handle_play_line,
                    runtime,
                    hub,
                    auth,
                    token,
                    line,
                    conn.connection_id,
                )
                await websocket.send_json({"type": "reply", **result})
                # Refresh map after authoritative move/action.
                await websocket.send_json(
                    {
                        "type": "map",
                        "map": build_map_view(
                            runtime.authority,
                            player_character_id=auth.player_character.id,
                            lod="near",
                            presence_by_room=hub.presence_by_room(),
                        ),
                    }
                )
                new_room = runtime.authority.get_player_room_id(
                    auth.player_character.id
                )
                hub.update_room(conn.connection_id, new_room)
        except WebSocketDisconnect:
            pass
        finally:
            writer_task.cancel()
            hub.detach(conn.connection_id)
            runtime.user_store.end_session(auth.session.id)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


def _handle_play_line(
    runtime: WorldRuntime,
    hub: SessionHub,
    auth,
    token: str,
    line: str,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Run one play line through WorldAuthority-backed PlayOrchestrator."""
    del token
    from world_sim.orchestrator.player_chat import parse_talk_target

    play = runtime.play_for(auth)
    text = line.strip()
    if not text:
        return {"ok": False, "reply": "Empty action.", "tool_names": []}

    lowered = text.lower()
    runtime.user_store.append_transcript(auth.session.id, "user", text)

    if play.in_player_chat:
        if lowered in {"end_chat", "end chat", "goodbye", "bye"}:
            reply = play.end_player_chat(reason="player")
            if connection_id:
                hub.release_player_chat(connection_id)
            runtime.user_store.append_transcript(auth.session.id, "assistant", reply)
            room_id = runtime.authority.get_player_room_id(auth.player_character.id)
            return {
                "ok": True,
                "reply": reply,
                "tool_names": [],
                "room_id": room_id,
            }
        result = play.handle_player_chat(text)
        runtime.user_store.append_transcript(auth.session.id, "assistant", result.reply)
        if result.ended and connection_id:
            hub.release_player_chat(connection_id)
        room_id = runtime.authority.get_player_room_id(auth.player_character.id)
        return {
            "ok": True,
            "reply": result.reply,
            "tool_names": result.tool_names,
            "room_id": room_id,
            "ended": result.ended,
        }

    target = parse_talk_target(text)
    if target and connection_id is not None:
        room_id = runtime.authority.get_player_room_id(auth.player_character.id)
        npc = runtime.authority.find_npc_by_name(target)
        if (
            npc is not None
            and room_id is not None
            and npc.current_room_id == room_id
        ):
            ok, reason = hub.try_claim_player_chat(connection_id, npc.npc_id)
            if not ok:
                return {
                    "ok": False,
                    "reply": reason,
                    "tool_names": [],
                    "room_id": room_id,
                }

    entered = play.try_begin_player_chat(text)
    if entered is not None:
        if not entered.ok and connection_id:
            hub.release_player_chat(connection_id)
        runtime.user_store.append_transcript(auth.session.id, "assistant", entered.message)
        room_id = runtime.authority.get_player_room_id(auth.player_character.id)
        return {
            "ok": entered.ok,
            "reply": entered.message,
            "tool_names": [],
            "room_id": room_id,
            "npc_id": entered.npc_id,
        }

    turn = play.handle_action(text)
    runtime.user_store.append_transcript(auth.session.id, "assistant", turn.reply)
    room_id = runtime.authority.get_player_room_id(auth.player_character.id)
    if connection_id:
        hub.update_room(connection_id, room_id)
    return {
        "ok": True,
        "reply": turn.reply,
        "tool_names": turn.tool_names,
        "room_id": room_id,
    }
