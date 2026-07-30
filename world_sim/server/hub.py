"""Live multi-session hub: presence, tokens, event fan-out, Player Chat soft-lease."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from world_sim.authority import (
    CHARACTER_ENTERED_ROOM,
    CHARACTER_LEFT_ROOM,
    CHARACTER_SAID,
    ITEM_TAKEN,
    NPC_MOVED,
    ROOM_REALIZED,
    RuntimeEvent,
    WorldAuthority,
)
from world_sim.models import AuthContext
from world_sim.utils.logger import get_logger

SendFn = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class LiveConnection:
    """One authenticated networked client bound to a player_character."""

    connection_id: str
    token: str
    auth: AuthContext
    send: SendFn
    room_id: str | None = None
    # Soft Player Chat focus (Phase 4a will harden to real leases).
    focused_npc_id: str | None = None


@dataclass
class SessionHub:
    """Tracks live connections for one shared world process."""

    authority: WorldAuthority
    connections: dict[str, LiveConnection] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)  # token -> connection_id
    # npc_id -> connection_id holding soft Player Chat focus
    player_chat_focus: dict[str, str] = field(default_factory=dict)
    _loop: asyncio.AbstractEventLoop | None = None
    _subscribed: bool = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        if not self._subscribed:
            self.authority.events.subscribe(self._on_runtime_event)
            self._subscribed = True

    def issue_token(self, auth: AuthContext) -> str:
        token = secrets.token_urlsafe(32)
        # Token may exist before WS connects; stash auth via pending map.
        self.tokens[token] = ""  # filled on attach
        self._pending_auth[token] = auth
        return token

    def __post_init__(self) -> None:
        self._pending_auth: dict[str, AuthContext] = {}
        self._logger = get_logger("hub")

    def take_pending_auth(self, token: str) -> AuthContext | None:
        return self._pending_auth.get(token)

    def attach(
        self,
        *,
        token: str,
        send: SendFn,
        room_id: str | None,
    ) -> LiveConnection:
        auth = self._pending_auth.get(token)
        if auth is None:
            raise ValueError("Unknown or expired token.")
        connection_id = secrets.token_urlsafe(12)
        conn = LiveConnection(
            connection_id=connection_id,
            token=token,
            auth=auth,
            send=send,
            room_id=room_id,
        )
        self.connections[connection_id] = conn
        self.tokens[token] = connection_id
        self._logger.info(
            "Attached connection=%s user=%s pc=%s room=%s",
            connection_id,
            auth.user.username,
            auth.player_character.id,
            room_id,
        )
        return conn

    def detach(self, connection_id: str) -> None:
        conn = self.connections.pop(connection_id, None)
        if conn is None:
            return
        self.tokens.pop(conn.token, None)
        self._pending_auth.pop(conn.token, None)
        if conn.focused_npc_id:
            holder = self.player_chat_focus.get(conn.focused_npc_id)
            if holder == connection_id:
                self.player_chat_focus.pop(conn.focused_npc_id, None)
            conn.focused_npc_id = None
        room = conn.room_id
        self._logger.info("Detached connection=%s", connection_id)
        if room:
            self._schedule(self._broadcast_presence(room))

    def get_by_token(self, token: str) -> LiveConnection | None:
        cid = self.tokens.get(token)
        if not cid:
            return None
        return self.connections.get(cid)

    def update_room(self, connection_id: str, room_id: str | None) -> None:
        conn = self.connections.get(connection_id)
        if conn is None:
            return
        old = conn.room_id
        conn.room_id = room_id
        rooms = {r for r in (old, room_id) if r}
        for room in rooms:
            self._schedule(self._broadcast_presence(room))

    def presence_in_room(self, room_id: str) -> list[dict[str, Any]]:
        roster: list[dict[str, Any]] = []
        for conn in self.connections.values():
            if conn.room_id != room_id:
                continue
            roster.append(
                {
                    "player_character_id": conn.auth.player_character.id,
                    "display_name": conn.auth.player_character.name,
                    "username": conn.auth.user.username,
                    "connection_id": conn.connection_id,
                }
            )
        roster.sort(key=lambda row: row["display_name"].lower())
        return roster

    def presence_by_room(self) -> dict[str, list[dict[str, Any]]]:
        rooms: dict[str, list[dict[str, Any]]] = {}
        for conn in self.connections.values():
            if not conn.room_id:
                continue
            rooms.setdefault(conn.room_id, []).append(
                {
                    "player_character_id": conn.auth.player_character.id,
                    "display_name": conn.auth.player_character.name,
                    "username": conn.auth.user.username,
                }
            )
        return rooms

    def try_claim_player_chat(
        self,
        connection_id: str,
        npc_id: str,
    ) -> tuple[bool, str]:
        """Soft exclusive focus until Phase 4a leases. Second client is refused."""
        holder = self.player_chat_focus.get(npc_id)
        if holder is not None and holder != connection_id:
            return (
                False,
                "That person is already in focused conversation with someone else. "
                "(Player Chat leases harden in Phase 4a; for now only one live focus.)",
            )
        self.player_chat_focus[npc_id] = connection_id
        conn = self.connections.get(connection_id)
        if conn is not None:
            conn.focused_npc_id = npc_id
        return True, ""

    def release_player_chat(self, connection_id: str) -> None:
        conn = self.connections.get(connection_id)
        if conn is None or not conn.focused_npc_id:
            return
        npc_id = conn.focused_npc_id
        if self.player_chat_focus.get(npc_id) == connection_id:
            self.player_chat_focus.pop(npc_id, None)
        conn.focused_npc_id = None

    def _on_runtime_event(self, event: RuntimeEvent) -> None:
        self._schedule(self._fan_out(event))

    def _schedule(self, coro: Awaitable[None]) -> None:
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            pass

    async def _fan_out(self, event: RuntimeEvent) -> None:
        room_ids = set(event.room_ids)
        if not room_ids:
            for key in ("room_id", "from_room_id", "to_room_id"):
                value = event.payload.get(key)
                if isinstance(value, str):
                    room_ids.add(value)

        # Scene-public: only sessions currently in an affected room.
        # Do not fan inventory details beyond payload already on the event.
        targets = [
            conn
            for conn in self.connections.values()
            if conn.room_id and conn.room_id in room_ids
        ]
        if not targets:
            return
        message = {
            "type": "event",
            "event": event.to_dict(),
        }
        for conn in targets:
            try:
                await conn.send(message)
            except Exception:  # noqa: BLE001 — isolate bad sockets
                self._logger.exception(
                    "Fan-out failed connection=%s", conn.connection_id
                )

        # Presence refresh when people move rooms.
        if event.event_type in {
            CHARACTER_ENTERED_ROOM,
            CHARACTER_LEFT_ROOM,
        }:
            for room in room_ids:
                await self._broadcast_presence(room)

    async def _broadcast_presence(self, room_id: str) -> None:
        roster = self.presence_in_room(room_id)
        message = {
            "type": "presence",
            "room_id": room_id,
            "roster": roster,
        }
        for conn in self.connections.values():
            if conn.room_id != room_id:
                continue
            try:
                await conn.send(message)
            except Exception:  # noqa: BLE001
                self._logger.exception(
                    "Presence send failed connection=%s", conn.connection_id
                )


# Event types imported for documentation / future filters
_FANOUT_HINTS = (
    CHARACTER_SAID,
    ITEM_TAKEN,
    NPC_MOVED,
    ROOM_REALIZED,
)
