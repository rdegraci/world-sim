"""Admin-only sandboxed chat_mode for one configured NPC."""

from __future__ import annotations

from dataclasses import dataclass, field

from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.base import ChatMessage, LLMAdapter
from world_sim.lore.chroma_manager import COLLECTION_NPC, ChromaManager
from world_sim.lore.seed import DEFAULT_CHAT_NPC_ID
from world_sim.models import AuthContext
from world_sim.orchestrator.presentation import npc_canonical_description
from world_sim.orchestrator.prompts import compose_chat_system_prompt
from world_sim.utils.logger import get_logger

CHAT_HELP = """\
chat_mode commands (admin only, sandboxed):
  help
  mode play / mode edit     Leave chat_mode
  who                       Show the configured chat NPC identity

Any other line is spoken to the configured NPC.
chat_mode reads canon but does not mutate world state, inventories, or lore.
"""


class ChatAccessError(Exception):
    """Raised when a non-admin attempts chat_mode operations."""


@dataclass
class ChatTurnResult:
    message: str
    ok: bool = True


@dataclass
class ChatOrchestrator:
    """Non-canonical NPC personality testing. No world mutation tools."""

    world: WorldStore
    lore: ChromaManager
    llm: LLMAdapter
    user_store: UserStore
    auth: AuthContext
    npc_id: str = DEFAULT_CHAT_NPC_ID
    _history: list[ChatMessage] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._logger = get_logger("chat")
        self.system_prompt = compose_chat_system_prompt()

    def assert_admin(self) -> None:
        if not self.auth.is_admin:
            raise ChatAccessError(
                "chat_mode is admin-only. Non-admin users cannot access sandboxed NPC chat."
            )

    def opening(self) -> str:
        self.assert_admin()
        npc = self.world.get_npc(self.npc_id)
        if npc is None:
            return (
                f"chat_mode configured NPC '{self.npc_id}' is missing from SQLite. "
                "Seed or create the NPC record before chatting."
            )
        description = npc_canonical_description(self.world, self.lore, npc.npc_id)
        self._logger.info(
            "Entering chat_mode npc_id=%s session_id=%s (sandbox, no mutations)",
            npc.npc_id,
            self.auth.session.id,
        )
        return (
            f"chat_mode sandbox with {npc.name} ({npc.npc_id}).\n"
            "This mode is non-canonical: replies do not mutate world/canon/inventories.\n"
            f"Current room (read-only context): {npc.current_room_id or 'unplaced'}\n\n"
            f"{description}"
        )

    def _context_block(self) -> str:
        npc = self.world.get_npc(self.npc_id)
        if npc is None:
            return "NPC record missing."
        lore_chunks: list[str] = []
        for key in npc.npc_lore:
            text = self.lore.get_lore(COLLECTION_NPC, key)
            lore_chunks.append(f"KEY {key}:\n{text or '(missing)'}")
        return (
            "SANDBOX CONTEXT (read-only)\n"
            f"npc_id={npc.npc_id}\n"
            f"name={npc.name}\n"
            f"current_room_id={npc.current_room_id}\n"
            f"condition={npc.condition}\n"
            f"npc_lore keys={npc.npc_lore}\n\n"
            + "\n\n".join(lore_chunks)
            + "\n\n"
            "Do not claim to change inventories, rooms, lore, or memory. "
            "If asked for persistence, say an authorized edit/world-builder path is required."
        )

    def handle(self, line: str) -> ChatTurnResult:
        self.assert_admin()
        text = line.strip()
        if not text:
            return ChatTurnResult(ok=False, message="Say something to the NPC.")
        if text.lower() in {"help", "?"}:
            return ChatTurnResult(message=CHAT_HELP)
        if text.lower() in {"who", "whoami"}:
            npc = self.world.get_npc(self.npc_id)
            if npc is None:
                return ChatTurnResult(ok=False, message="Configured NPC missing.")
            return ChatTurnResult(
                message=(
                    f"npc_id={npc.npc_id} name={npc.name} "
                    f"room={npc.current_room_id} lore_keys={npc.npc_lore}"
                )
            )

        # Snapshot mutable world facts before the call to prove no mutation.
        before_npc = self.world.get_npc(self.npc_id)
        before_minutes = self.world.get_minutes_elapsed()
        before_items = [
            (item.id, item.location_kind, item.location_id)
            for item in self.world.list_player_items(self.auth.player_character.id)
        ]

        messages = [
            ChatMessage(role="system", content=self._context_block()),
            *self._history,
            ChatMessage(role="user", content=text),
        ]
        self._logger.info(
            "chat_mode turn npc=%s user_chars=%s history=%s",
            self.npc_id,
            len(text),
            len(self._history),
        )
        try:
            response = self.llm.complete(
                system=self.system_prompt,
                messages=messages,
                tools=None,  # No mutation tools in chat_mode.
            )
        except Exception as exc:
            self._logger.exception("chat_mode LLM failed: %s", exc)
            return ChatTurnResult(
                ok=False,
                message=f"chat_mode narration failed: {exc}",
            )

        reply = response.text.strip() or (
            f"{before_npc.name if before_npc else 'NPC'}: ..."
        )

        # Guard: refuse to apply any accidental tool calls if a provider returns them.
        if response.tool_calls:
            self._logger.warning(
                "chat_mode ignored %s tool call(s); sandbox forbids mutations",
                len(response.tool_calls),
            )

        after_npc = self.world.get_npc(self.npc_id)
        after_minutes = self.world.get_minutes_elapsed()
        after_items = [
            (item.id, item.location_kind, item.location_id)
            for item in self.world.list_player_items(self.auth.player_character.id)
        ]
        if (
            before_npc != after_npc
            or before_minutes != after_minutes
            or before_items != after_items
        ):
            self._logger.error("chat_mode detected unexpected world mutation")
            return ChatTurnResult(
                ok=False,
                message=(
                    "chat_mode abort: unexpected world mutation detected. "
                    "No further sandbox reply applied."
                ),
            )

        self._history.append(ChatMessage(role="user", content=text))
        self._history.append(ChatMessage(role="assistant", content=reply))
        self.user_store.append_transcript(self.auth.session.id, "assistant", reply)
        return ChatTurnResult(message=reply)
