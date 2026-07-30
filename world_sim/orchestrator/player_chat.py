"""Focused in-play Player Chat sub-loop (conversation-only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from world_sim.db.user_store import UserStore
from world_sim.db.world_store import NpcRecord, WorldStore
from world_sim.llm.base import ChatMessage, LLMAdapter
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_NPC,
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)
from world_sim.lore.seed import SYSTEM_LORE_KEY
from world_sim.models import AuthContext
from world_sim.orchestrator.presentation import npc_canonical_description
from world_sim.orchestrator.prompts import compose_player_chat_system_prompt
from world_sim.tools.definitions import PLAYER_CHAT_TOOLS
from world_sim.utils.logger import get_logger

TALK_PATTERN = re.compile(
    r"^(?:talk(?:\s+to)?|speak(?:\s+to|\s+with)?|chat(?:\s+with)?)\s+(.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlayerChatTurnResult:
    reply: str
    ended: bool = False
    tool_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlayerChatEnterResult:
    ok: bool
    message: str
    npc_id: str | None = None


def parse_talk_target(line: str) -> str | None:
    """Return NPC name query if line is a talk/speak intent, else None."""
    match = TALK_PATTERN.match(line.strip())
    if not match:
        return None
    target = match.group(1).strip().strip("\"'")
    # Drop leading articles.
    target = re.sub(r"^(the|a|an)\s+", "", target, flags=re.IGNORECASE).strip()
    return target or None


class PlayerChatOrchestrator:
    """Canonical, scene-bound one-on-one NPC conversation inside play_mode."""

    def __init__(
        self,
        *,
        world: WorldStore,
        lore: ChromaManager,
        llm: LLMAdapter,
        user_store: UserStore,
        auth: AuthContext,
    ) -> None:
        self.world = world
        self.lore = lore
        self.llm = llm
        self.user_store = user_store
        self.auth = auth
        self.system_prompt = compose_player_chat_system_prompt()
        self.active_npc_id: str | None = None
        self._history: list[ChatMessage] = []
        self._logger = get_logger("player_chat")

    @property
    def active(self) -> bool:
        return self.active_npc_id is not None

    def try_enter(self, line: str) -> PlayerChatEnterResult | None:
        """If line is a talk intent, attempt to start Player Chat. Else None."""
        target = parse_talk_target(line)
        if target is None:
            return None
        room_id = self.world.get_player_room_id(self.auth.player_character.id)
        if room_id is None:
            return PlayerChatEnterResult(
                ok=False,
                message="You are not placed in a room, so there is no one to talk to.",
            )
        npc = self._find_present_npc(room_id, target)
        if npc is None:
            return PlayerChatEnterResult(
                ok=False,
                message=(
                    f"You look for someone to talk to matching '{target}', but no such "
                    "person is here with you now."
                ),
            )
        return self._begin(npc)

    def _begin(self, npc: NpcRecord) -> PlayerChatEnterResult:
        self.active_npc_id = npc.npc_id
        self._history.clear()
        description = npc_canonical_description(self.world, self.lore, npc.npc_id)
        recap = description.split(".")[0].strip() if description else npc.name
        opening = (
            f"You turn toward {npc.name}. {recap}.\n"
            f'{npc.name} regards you and waits.\n'
            f"(You are now talking with {npc.name}. Type end_chat to stop.)"
        )
        self._logger.info(
            "Player Chat started npc=%s player=%s room=%s",
            npc.npc_id,
            self.auth.player_character.id,
            npc.current_room_id,
        )
        return PlayerChatEnterResult(ok=True, message=opening, npc_id=npc.npc_id)

    def end(self, *, reason: str = "player") -> str:
        npc_id = self.active_npc_id
        npc = self.world.get_npc(npc_id) if npc_id else None
        name = npc.name if npc else (npc_id or "them")
        self.active_npc_id = None
        self._history.clear()
        self._logger.info("Player Chat ended npc=%s reason=%s", npc_id, reason)
        if reason == "unavailable":
            return (
                f"The conversation fades — {name} is no longer here to speak with.\n"
                "(You return to normal play.)"
            )
        return (
            f"You finish speaking with {name} and turn back to the room.\n"
            "(You return to normal play. Type look to reorient.)"
        )

    def handle(self, line: str) -> PlayerChatTurnResult:
        text = line.strip()
        if not self.active_npc_id:
            return PlayerChatTurnResult(
                reply="You are not in a focused conversation.",
                ended=True,
            )
        if text.lower() in {"end_chat", "end chat", "stop talking", "goodbye"}:
            return PlayerChatTurnResult(reply=self.end(reason="player"), ended=True)

        if not self._npc_still_available():
            return PlayerChatTurnResult(
                reply=self.end(reason="unavailable"),
                ended=True,
            )

        before = self._snapshot_world()
        context = self._context_block()
        messages = [
            ChatMessage(role="system", content=context),
            *self._history,
            ChatMessage(role="user", content=text),
        ]
        self._logger.info(
            "Player Chat turn npc=%s chars=%s history=%s",
            self.active_npc_id,
            len(text),
            len(self._history),
        )
        try:
            response = self.llm.complete(
                system=self.system_prompt,
                messages=messages,
                tools=PLAYER_CHAT_TOOLS,
            )
        except Exception as exc:
            self._logger.exception("Player Chat LLM failed: %s", exc)
            return PlayerChatTurnResult(
                reply=f"The conversation falters for a moment. ({exc})",
            )

        tool_names: list[str] = []
        ended = False
        end_note = ""
        for call in response.tool_calls:
            tool_names.append(call.name)
            if call.name == "end_player_chat":
                ended = True
                reason = str(call.arguments.get("reason") or "conversation_over")
                end_note = self.end(reason=reason)
            else:
                self._logger.warning(
                    "Player Chat ignored non-allowed tool %s", call.name
                )

        if not self._snapshots_equal(before, self._snapshot_world()):
            self._logger.error("Player Chat detected unexpected world mutation")
            self.active_npc_id = None
            self._history.clear()
            return PlayerChatTurnResult(
                reply=(
                    "Player Chat abort: unexpected world mutation detected. "
                    "Conversation ended without applying invented changes."
                ),
                ended=True,
                tool_names=tool_names,
            )

        reply = response.text.strip()
        if not reply and not ended:
            npc = self.world.get_npc(self.active_npc_id)
            name = npc.name if npc else "They"
            reply = f"{name}: ..."

        if ended:
            parts = [part for part in (reply, end_note) if part]
            reply = "\n\n".join(parts) if parts else end_note
        else:
            self._history.append(ChatMessage(role="user", content=text))
            self._history.append(ChatMessage(role="assistant", content=reply))

        self.user_store.append_transcript(self.auth.session.id, "assistant", reply)
        return PlayerChatTurnResult(reply=reply, ended=ended, tool_names=tool_names)

    def _find_present_npc(self, room_id: str, query: str) -> NpcRecord | None:
        needle = query.strip().lower()
        for npc in self.world.list_npcs_in_room(room_id):
            if needle in npc.name.lower() or needle == npc.npc_id.lower():
                return npc
            # Allow "mrs hale" vs "Mrs. Hale"
            compact_name = re.sub(r"[^a-z0-9]+", "", npc.name.lower())
            compact_query = re.sub(r"[^a-z0-9]+", "", needle)
            if compact_query and compact_query in compact_name:
                return npc
        return None

    def _npc_still_available(self) -> bool:
        if not self.active_npc_id:
            return False
        npc = self.world.get_npc(self.active_npc_id)
        if npc is None:
            return False
        room_id = self.world.get_player_room_id(self.auth.player_character.id)
        if room_id is None or npc.current_room_id != room_id:
            return False
        return True

    def _context_block(self) -> str:
        assert self.active_npc_id is not None
        npc = self.world.get_npc(self.active_npc_id)
        room_id = self.world.get_player_room_id(self.auth.player_character.id)
        system_lore = self.lore.get_lore(COLLECTION_SYSTEM, SYSTEM_LORE_KEY)
        room = self.world.get_room(room_id) if room_id else None
        room_lore = (
            self.lore.get_lore(COLLECTION_ROOM, room.lore_key) if room else None
        )
        room_items = self.world.list_items_in_room(room_id) if room_id else []
        present_npcs = self.world.list_npcs_in_room(room_id) if room_id else []
        player_items = self.world.list_player_items(self.auth.player_character.id)

        lore_chunks: list[str] = []
        if npc:
            for key in npc.npc_lore:
                text = self.lore.get_lore(COLLECTION_NPC, key)
                lore_chunks.append(f"KEY {key}:\n{text or '(missing)'}")

        item_lines = []
        for item in room_items:
            item_lore = (
                self.lore.get_lore(COLLECTION_ITEM, item.definition_key)
                if item.definition_key
                else None
            )
            item_lines.append(
                f"- #{item.id} {item.name} lore_key={item.definition_key} "
                f"canon={bool(item_lore)}"
            )

        inv_lines = [
            f"- #{item.id} {item.name} ({item.definition_key})"
            for item in player_items
        ] or ["- empty"]

        npc_lines = [
            f"- {other.npc_id}: {other.name}" for other in present_npcs
        ] or ["- none"]

        return (
            "PLAYER CHAT CONTEXT (read-only; conversation-only MVP)\n"
            f"active_npc_id={self.active_npc_id}\n"
            f"npc_name={npc.name if npc else '?'}\n"
            f"npc_condition={npc.condition if npc else '?'}\n"
            f"npc_lore keys={npc.npc_lore if npc else []}\n\n"
            + "\n\n".join(lore_chunks)
            + "\n\n"
            f"System lore:\n{system_lore or '(missing)'}\n\n"
            f"Current room id={room_id} name={room.name if room else '?'}\n"
            f"Room lore:\n{room_lore or '(missing)'}\n"
            f"Exits: {self.world.list_exits(room_id) if room_id else {}}\n"
            f"Items visible in room:\n"
            + ("\n".join(item_lines) if item_lines else "- none")
            + "\n"
            f"People present:\n"
            + "\n".join(npc_lines)
            + "\n"
            f"Player inventory (read-only):\n"
            + "\n".join(inv_lines)
            + "\n\n"
            "NPC inventory: (not modeled beyond presence; do not invent handoffs)\n"
            "Hard rules: do not mutate world/inventories/canon. "
            "Refuse unsupported player assertions of entities, exits, items, or NPCs. "
            "Use end_player_chat only to end the focused loop. "
            "Type end_chat is also handled by the runtime."
        )

    def _snapshot_world(self) -> tuple:
        pc = self.auth.player_character.id
        npc = self.world.get_npc(self.active_npc_id) if self.active_npc_id else None
        items = [
            (item.id, item.location_kind, item.location_id)
            for item in self.world.list_player_items(pc)
        ]
        room_id = self.world.get_player_room_id(pc)
        room_items = []
        if room_id:
            room_items = [
                (item.id, item.location_kind, item.location_id)
                for item in self.world.list_items_in_room(room_id)
            ]
        return (
            npc,
            self.world.get_minutes_elapsed(),
            tuple(items),
            room_id,
            tuple(room_items),
        )

    @staticmethod
    def _snapshots_equal(before: tuple, after: tuple) -> bool:
        return before == after
