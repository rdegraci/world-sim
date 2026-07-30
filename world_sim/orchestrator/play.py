"""play_mode turn orchestration: context → LLM → tools → reply."""

from __future__ import annotations

import re
from dataclasses import dataclass

from world_sim.authority import WorldAuthority
from world_sim.config import WorldExpansionSettings
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.base import ChatMessage, LLMAdapter
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.models import AuthContext
from world_sim.orchestrator.context_builder import ContextBuilder
from world_sim.orchestrator.player_chat import (
    PlayerChatEnterResult,
    PlayerChatOrchestrator,
    PlayerChatTurnResult,
)
from world_sim.orchestrator.presentation import present_room
from world_sim.orchestrator.prompts import compose_play_system_prompt
from world_sim.tools.definitions import PLAY_TOOLS
from world_sim.tools.implementations import PlayTools, normalize_direction
from world_sim.utils.logger import get_logger

MOVE_PATTERN = re.compile(
    r"^(?:go|walk|move)\s+(\S+)$|^(north|south|east|west|up|down|n|s|e|w|u|d)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlayTurnResult:
    reply: str
    tool_names: list[str]


class PlayOrchestrator:
    """Grounded play loop for a single authenticated player character."""

    def __init__(
        self,
        *,
        world: WorldAuthority | WorldStore,
        lore: ChromaManager,
        llm: LLMAdapter,
        user_store: UserStore,
        auth: AuthContext,
        expansion: WorldExpansionSettings | None = None,
    ) -> None:
        # Play mutations always go through WorldAuthority (SQLite backend today).
        if isinstance(world, WorldAuthority):
            self.authority = world
        else:
            self.authority = WorldAuthority(world)
        self.world = self.authority
        self.lore = lore
        self.llm = llm
        self.user_store = user_store
        self.auth = auth
        self.expansion = expansion or WorldExpansionSettings()
        self.context_builder = ContextBuilder(self.authority.store, lore)
        self.tools = PlayTools(
            self.authority,
            lore,
            player_character_id=auth.player_character.id,
            expansion=self.expansion,
        )
        self.system_prompt = compose_play_system_prompt()
        self.player_chat = PlayerChatOrchestrator(
            world=self.authority.store,
            lore=lore,
            llm=llm,
            user_store=user_store,
            auth=auth,
        )
        self._logger = get_logger("play")

    @property
    def in_player_chat(self) -> bool:
        return self.player_chat.active

    def try_begin_player_chat(self, line: str) -> PlayerChatEnterResult | None:
        return self.player_chat.try_enter(line)

    def handle_player_chat(self, line: str) -> PlayerChatTurnResult:
        return self.player_chat.handle(line)

    def end_player_chat(self, *, reason: str = "player") -> str:
        return self.player_chat.end(reason=reason)

    def opening_presentation(self) -> str:
        room_id = self.world.get_player_room_id(self.auth.player_character.id)
        if room_id is None:
            return "You are not placed in the world yet."
        return present_room(
            self.authority.store,
            self.lore,
            player_character_id=self.auth.player_character.id,
            room_id=room_id,
            force_full=False,
            show_pending_stubs=self.expansion.dynamic_expansion,
        )

    def handle_action(self, action: str) -> PlayTurnResult:
        action = action.strip()
        # Clear movement intents bypass the LLM so frontier stubs and real exits
        # are not narrated away when the model ignores tools.
        move_direction = self._parse_move_direction(action)
        if move_direction is not None:
            result = self.tools.move_player({"direction": move_direction})
            self._logger.info(
                "Direct move player=%s direction=%s ok=%s",
                self.auth.player_character.id,
                move_direction,
                result.ok,
            )
            self.user_store.append_transcript(
                self.auth.session.id,
                "assistant",
                result.message,
            )
            return PlayTurnResult(
                reply=result.message,
                tool_names=["move_player"],
            )

        context = self.context_builder.build(
            self.auth.player_character.id,
            include_frontier_stubs=self.expansion.dynamic_expansion,
        )
        messages = [
            ChatMessage(role="system", content=context.text),
            ChatMessage(role="user", content=action),
        ]
        self._logger.info(
            "Play turn player=%s room=%s action=%r",
            self.auth.player_character.id,
            context.room_id,
            action,
        )
        try:
            response = self.llm.complete(
                system=self.system_prompt,
                messages=messages,
                tools=PLAY_TOOLS,
            )
        except Exception as exc:
            self._logger.exception("LLM call failed: %s", exc)
            reply = (
                "The narration service failed for that action. "
                f"Details: {exc}\n"
                "DM: Your session is still active. Try again, check grok_model "
                "in config.yaml, or set WORLD_SIM_LLM=fake for offline play."
            )
            self.user_store.append_transcript(
                self.auth.session.id,
                "assistant",
                reply,
            )
            return PlayTurnResult(reply=reply, tool_names=[])

        tool_names: list[str] = []
        tool_messages: list[str] = []
        for call in response.tool_calls:
            tool_names.append(call.name)
            result = self.tools.execute(call.name, call.arguments)
            tool_messages.append(result.message)
            self._logger.info(
                "Tool %s ok=%s args=%s",
                call.name,
                result.ok,
                call.arguments,
            )

        parts = [part for part in tool_messages if part]
        if response.text.strip():
            if not parts:
                parts.append(response.text.strip())
            elif not tool_names:
                parts.append(response.text.strip())

        if not parts:
            parts.append(
                "Nothing definite happens. The manor waits on a clearer action."
            )

        reply = "\n\n".join(parts)
        self.user_store.append_transcript(
            self.auth.session.id,
            "assistant",
            reply,
        )
        return PlayTurnResult(reply=reply, tool_names=tool_names)

    @staticmethod
    def _parse_move_direction(action: str) -> str | None:
        match = MOVE_PATTERN.match(action.strip())
        if not match:
            return None
        raw = match.group(1) or match.group(2)
        return normalize_direction(raw)
