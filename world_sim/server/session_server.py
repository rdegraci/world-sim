"""Local interactive session loop for the World-Sim MVP."""

from __future__ import annotations

import sys
from collections.abc import Callable

from world_sim.db.user_store import UserStore
from world_sim.models import AuthContext
from world_sim.utils.logger import get_logger

HELP_TEXT = """\
Commands:
  help   Show this help text
  whoami Show the authenticated user and player character
  quit   Exit World-Sim
  exit   Exit World-Sim

Play, chat, and edit modes are not wired up yet.
Type actions here once the local session runtime is implemented.
"""

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def run_session(
    *,
    auth: AuthContext | None = None,
    store: UserStore | None = None,
    input_fn: InputFn = input,
    output_fn: OutputFn = print,
) -> int:
    """Run the local CLI session shell until the user exits.

    Returns an exit code suitable for ``sys.exit``.
    """
    logger = get_logger("session")
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

    exit_code = 0
    try:
        while True:
            try:
                raw = input_fn("> ")
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
                output_fn(HELP_TEXT)
                continue
            if command == "whoami":
                if auth is None:
                    output_fn("Not signed in.")
                else:
                    output_fn(
                        f"user={auth.user.username} role={auth.user.role} "
                        f"user_id={auth.user.id} "
                        f"player_character_id={auth.player_character.id} "
                        f"session_id={auth.session.id}"
                    )
                continue

            output_fn(
                "Authenticated shell ready. "
                "Play, chat, and edit modes are not wired up yet. "
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
