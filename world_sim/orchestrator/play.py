"""play_mode turn orchestration: context → LLM → tools → reply."""

from __future__ import annotations

from dataclasses import dataclass

from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.base import ChatMessage, LLMAdapter
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.models import AuthContext
from world_sim.orchestrator.context_builder import ContextBuilder
from world_sim.orchestrator.presentation import present_room
from world_sim.orchestrator.prompts import compose_play_system_prompt
from world_sim.tools.definitions import PLAY_TOOLS
from world_sim.tools.implementations import PlayTools
from world_sim.utils.logger import get_logger


@dataclass(frozen=True)
class PlayTurnResult:
    reply: str
    tool_names: list[str]


class PlayOrchestrator:
    """Grounded play loop for a single authenticated player character."""

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
        self.context_builder = ContextBuilder(world, lore)
        self.tools = PlayTools(
            world,
            lore,
            player_character_id=auth.player_character.id,
        )
        self.system_prompt = compose_play_system_prompt()
        self._logger = get_logger("play")

    def opening_presentation(self) -> str:
        room_id = self.world.get_player_room_id(self.auth.player_character.id)
        if room_id is None:
            return "You are not placed in the world yet."
        return present_room(
            self.world,
            self.lore,
            player_character_id=self.auth.player_character.id,
            room_id=room_id,
            force_full=False,
        )

    def handle_action(self, action: str) -> PlayTurnResult:
        action = action.strip()
        context = self.context_builder.build(self.auth.player_character.id)
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
            # If tools already produced presentation, keep LLM text as optional color
            # only when no tools ran.
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
