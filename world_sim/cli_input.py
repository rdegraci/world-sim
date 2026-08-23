"""CLI line input: readline history for play, prompt_toolkit for admin."""

from __future__ import annotations

import atexit
import sys
from pathlib import Path
from typing import Literal

InputKind = Literal["play", "admin"]

_play_history_ready = False
_play_history_path: Path | None = None
_admin_session_key: Path | None = None
_admin_session: object | None = None

# First-token completion for admin surfaces (edit, chat, world-builder).
_ADMIN_COMMANDS: tuple[str, ...] = (
    "add_frontier_stub",
    "add_item_lore",
    "add_npc",
    "add_npc_lore",
    "add_room_lore",
    "add_system_lore",
    "append_npc_lore",
    "apply",
    "apply_seed_plan",
    "approve_draft",
    "attach_item_lore",
    "attach_npc_lore",
    "attach_room_lore",
    "connect_rooms",
    "create_item_lore",
    "create_npc",
    "create_npc_lore",
    "create_room_lore",
    "create_system_lore",
    "delete_item_lore",
    "delete_npc",
    "delete_room_lore",
    "delete_system_lore",
    "discover_lore",
    "edit_item_lore",
    "edit_npc",
    "edit_npc_lore",
    "edit_room_lore",
    "edit_system_lore",
    "end_chat",
    "exit",
    "help",
    "inventory",
    "list_drafts",
    "list_frontier_stubs",
    "list_item_lore",
    "list_items",
    "list_lore",
    "list_npc_lore",
    "list_npcs",
    "list_plans",
    "list_room_lore",
    "list_rooms",
    "list_system_lore",
    "look",
    "mode",
    "open_plan",
    "place_item",
    "place_npc",
    "preview_seed_plan",
    "propose_discovered",
    "propose_from_brief",
    "propose_items_from_lore",
    "propose_npcs_from_lore",
    "propose_rooms_from_lore",
    "quit",
    "reject_draft",
    "revise_npc_lore",
    "talk",
    "upsert_lore",
    "validate_world",
    "view_draft",
    "view_item_lore",
    "view_npc",
    "view_room_lore",
    "view_system_lore",
    "who",
    "whoami",
)


def is_interactive() -> bool:
    """True when stdin/stdout are a TTY (real terminal session)."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_line(
    prompt: str,
    *,
    kind: InputKind = "play",
    history_dir: Path | None = None,
) -> str:
    """Read one line from the user with mode-appropriate editing support."""
    if not is_interactive():
        return input(prompt)
    if kind == "admin":
        return _prompt_admin(prompt, history_dir=history_dir)
    return _prompt_play(prompt, history_dir=history_dir)


def _history_file(history_dir: Path | None, name: str) -> Path | None:
    if history_dir is None:
        return None
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / name


def _ensure_readline(history_dir: Path | None) -> None:
    global _play_history_ready, _play_history_path
    if _play_history_ready:
        return
    _play_history_ready = True
    try:
        import readline
    except ImportError:
        return

    path = _history_file(history_dir, "play_history")
    _play_history_path = path
    if path is not None and path.exists():
        try:
            readline.read_history_file(str(path))
        except OSError:
            pass
    readline.set_history_length(1000)

    if path is not None:

        def _save_play_history() -> None:
            if _play_history_path is None:
                return
            try:
                readline.write_history_file(str(_play_history_path))
            except OSError:
                pass

        atexit.register(_save_play_history)


def _remember_play_line(line: str) -> None:
    stripped = line.strip()
    if not stripped:
        return
    try:
        import readline
    except ImportError:
        return
    readline.add_history(stripped)


def _prompt_play(prompt: str, *, history_dir: Path | None) -> str:
    _ensure_readline(history_dir)
    line = input(prompt)
    _remember_play_line(line)
    return line


def _admin_prompt_session(history_dir: Path | None):
    global _admin_session, _admin_session_key
    key = history_dir or Path(".")
    if _admin_session is not None and _admin_session_key == key:
        return _admin_session

    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import FileHistory, InMemoryHistory

    path = _history_file(history_dir, "admin_history")
    history = FileHistory(str(path)) if path is not None else InMemoryHistory()
    completer = WordCompleter(list(_ADMIN_COMMANDS), ignore_case=True)
    session = PromptSession(history=history, completer=completer)
    _admin_session_key = key
    _admin_session = session
    return session


def _prompt_admin(prompt: str, *, history_dir: Path | None) -> str:
    session = _admin_prompt_session(history_dir)
    return session.prompt(prompt)
