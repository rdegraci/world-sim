"""Local interactive session loop for the World-Sim MVP."""

from __future__ import annotations

import sys
from collections.abc import Callable


HELP_TEXT = """\
Commands:
  help   Show this help text
  quit   Exit World-Sim
  exit   Exit World-Sim

Play, chat, and edit modes are not wired up yet.
Type actions here once the local session runtime is implemented.
"""


def run_session(
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    """Run the local CLI session shell until the user exits.

    Returns an exit code suitable for ``sys.exit``.
    """
    output_fn("World-Sim local session")
    output_fn("Type 'help' for commands, or 'quit' to exit.")
    output_fn("")

    while True:
        try:
            raw = input_fn("> ")
        except EOFError:
            output_fn("")
            output_fn("Goodbye.")
            return 0
        except KeyboardInterrupt:
            output_fn("")
            output_fn("Interrupted. Goodbye.")
            return 130

        line = raw.strip()
        if not line:
            continue

        command = line.lower()
        if command in {"quit", "exit", "q"}:
            output_fn("Goodbye.")
            return 0
        if command in {"help", "?"}:
            output_fn(HELP_TEXT)
            continue

        output_fn(
            "Session runtime is not implemented yet. "
            "Use 'help' for available commands."
        )


def main() -> int:
    """Entry point used by the packaged CLI."""
    return run_session()


if __name__ == "__main__":
    sys.exit(main())
