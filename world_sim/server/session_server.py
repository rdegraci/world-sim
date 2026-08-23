"""Local interactive session loop for the World-Sim MVP."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from world_sim.cli_input import InputKind, prompt_line
from world_sim.db.user_store import UserStore
from world_sim.models import AuthContext
from world_sim.orchestrator.chat import ChatAccessError, ChatOrchestrator
from world_sim.orchestrator.edit import EditAccessError, EditOrchestrator
from world_sim.orchestrator.play import PlayOrchestrator
from world_sim.utils.logger import get_logger

PLAY_HELP = """\
Commands:
  help       Show this help text
  whoami     Show the authenticated user and player character
  mode play  Stay in / return to play_mode
  mode edit  Enter admin-only edit_mode (admin only)
  mode chat  Enter admin-only sandboxed chat_mode (admin only)
  look       Look at the current room (full canonical description)
  inventory  List carried items
  talk to <npc>   Start focused in-play Player Chat with a present NPC
  end_chat   End focused Player Chat (while talking)
  quit       Exit World-Sim
  exit       Exit World-Sim

Other lines are treated as play_mode actions (move, take, examine, wait, ...).
While in Player Chat, lines are spoken to the active NPC.
"""

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def _mode_prompt(mode: str, *, in_player_chat: bool = False) -> str:
    if mode == "edit":
        return "edit> "
    if mode == "chat":
        return "chat> "
    if in_player_chat:
        return "talk> "
    return "> "


def _read_line(
    *,
    mode: str,
    in_player_chat: bool,
    input_fn: InputFn | None,
    history_dir: Path | None,
) -> str:
    prompt = _mode_prompt(mode, in_player_chat=in_player_chat)
    if input_fn is not None:
        return input_fn(prompt)
    kind: InputKind = "admin" if mode in {"edit", "chat"} else "play"
    return prompt_line(prompt, kind=kind, history_dir=history_dir)


def run_session(
    *,
    auth: AuthContext | None = None,
    store: UserStore | None = None,
    play: PlayOrchestrator | None = None,
    edit: EditOrchestrator | None = None,
    chat: ChatOrchestrator | None = None,
    input_fn: InputFn | None = None,
    history_dir: Path | None = None,
    output_fn: OutputFn = print,
) -> int:
    """Run the local CLI session shell until the user exits.

    Returns an exit code suitable for ``sys.exit``.
    """
    logger = get_logger("session")
    mode = "play"

    if auth is not None:
        output_fn(
            f"World-Sim local session — signed in as {auth.user.username} "
            f"({auth.user.role})"
        )
        output_fn(
            f"Player character id={auth.player_character.id} "
            f"name={auth.player_character.name}"
        )
        output_fn(f"Session id={auth.session.id}")
    else:
        output_fn("World-Sim local session")
    output_fn("Type 'help' for commands, or 'quit' to exit.")
    output_fn("")

    def _record(speaker: str, content: str) -> None:
        if auth is None or store is None:
            return
        store.append_transcript(auth.session.id, speaker, content)

    if auth is not None and store is not None:
        _record(
            "system",
            f"Session started for user={auth.user.username} "
            f"player_character_id={auth.player_character.id}",
        )

    if play is not None:
        opening = play.opening_presentation()
        output_fn(opening)
        output_fn("")
        _record("assistant", opening)

    exit_code = 0
    try:
        while True:
            try:
                in_player_chat = bool(play is not None and play.in_player_chat)
                raw = _read_line(
                    mode=mode,
                    in_player_chat=in_player_chat,
                    input_fn=input_fn,
                    history_dir=history_dir,
                )
            except EOFError:
                output_fn("")
                output_fn("Goodbye.")
                exit_code = 0
                break
            except KeyboardInterrupt:
                output_fn("")
                output_fn("Interrupted. Goodbye.")
                exit_code = 130
                break

            line = raw.strip()
            if not line:
                continue

            _record("user", line)
            command = line.lower()
            if command in {"quit", "exit", "q"}:
                output_fn("Goodbye.")
                _record("system", "Session ended by user.")
                exit_code = 0
                break
            if command in {"help", "?"}:
                if mode == "edit" and edit is not None:
                    output_fn(edit.handle("help").message)
                elif mode == "chat" and chat is not None:
                    output_fn(chat.handle("help").message)
                else:
                    output_fn(PLAY_HELP)
                continue
            if command == "whoami":
                if auth is None:
                    output_fn("Not signed in.")
                else:
                    output_fn(
                        f"user={auth.user.username} role={auth.user.role} "
                        f"user_id={auth.user.id} "
                        f"player_character_id={auth.player_character.id} "
                        f"session_id={auth.session.id} mode={mode}"
                    )
                continue
            if command.startswith("mode "):
                target = command.split(maxsplit=1)[1].strip()
                previous = mode
                if play is not None and play.in_player_chat:
                    ended = play.end_player_chat(reason="mode_switch")
                    output_fn(ended)
                    _record("assistant", ended)
                if target == "play":
                    mode = "play"
                    logger.info("Mode boundary %s -> play", previous)
                    output_fn("Switched to play_mode.")
                    continue
                if target == "edit":
                    if auth is None or not auth.is_admin:
                        logger.info("Denied edit_mode for non-admin")
                        output_fn(
                            "edit_mode is admin-only. "
                            "Non-admin users cannot access canon operations."
                        )
                        continue
                    if edit is None:
                        output_fn("edit_mode is not available in this session.")
                        continue
                    mode = "edit"
                    logger.info("Mode boundary %s -> edit", previous)
                    output_fn(
                        "Switched to edit_mode. Type 'help' for constrained canon commands."
                    )
                    continue
                if target == "chat":
                    if auth is None or not auth.is_admin:
                        logger.info("Denied chat_mode for non-admin")
                        output_fn(
                            "chat_mode is admin-only. "
                            "Non-admin users cannot access sandboxed NPC chat."
                        )
                        continue
                    if chat is None:
                        output_fn("chat_mode is not available in this session.")
                        continue
                    mode = "chat"
                    logger.info(
                        "Mode boundary %s -> chat npc=%s",
                        previous,
                        chat.npc_id,
                    )
                    opening = chat.opening()
                    output_fn(opening)
                    _record("assistant", opening)
                    continue
                output_fn("Unknown mode. Use 'mode play', 'mode edit', or 'mode chat'.")
                continue
            if command == "inventory":
                if play is None:
                    output_fn("Play runtime is not available.")
                    continue
                if play.in_player_chat:
                    output_fn(
                        "You are in focused conversation. "
                        "Type end_chat first, or ask the NPC about what you carry."
                    )
                    continue
                items = play.world.list_player_items(play.auth.player_character.id)
                if not items:
                    output_fn("You are carrying nothing.")
                else:
                    for item in items:
                        output_fn(f"- #{item.id} {item.name}")
                continue

            if mode == "edit":
                if edit is None:
                    output_fn("edit_mode is not available in this session.")
                    continue
                try:
                    result = edit.handle(line)
                except EditAccessError as exc:
                    output_fn(str(exc))
                    mode = "play"
                    continue
                output_fn(result.message)
                _record("assistant", result.message)
                continue

            if mode == "chat":
                if chat is None:
                    output_fn("chat_mode is not available in this session.")
                    continue
                try:
                    result = chat.handle(line)
                except ChatAccessError as exc:
                    output_fn(str(exc))
                    mode = "play"
                    continue
                output_fn(result.message)
                continue

            if play is not None:
                if play.in_player_chat:
                    result = play.handle_player_chat(line)
                    output_fn(result.reply)
                    continue
                entered = play.try_begin_player_chat(line)
                if entered is not None:
                    output_fn(entered.message)
                    _record("assistant", entered.message)
                    continue
                result = play.handle_action(line)
                output_fn(result.reply)
                continue

            output_fn(
                "Authenticated shell ready. "
                "Play runtime is not wired in this session. "
                "Use 'help' for available commands."
            )
    finally:
        if auth is not None and store is not None:
            ended = store.end_session(auth.session.id)
            logger.info(
                "Ended session id=%s status=%s ended_at=%s",
                ended.id,
                ended.status,
                ended.ended_at,
            )

    return exit_code


def main() -> int:
    """Entry point used when running the module directly without auth."""
    return run_session()


if __name__ == "__main__":
    sys.exit(main())
