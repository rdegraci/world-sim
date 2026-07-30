"""Prompt loading for mode overlays."""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt_file(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8").strip()


def compose_play_system_prompt() -> str:
    """Compose core + play_mode. Falls back to assembled system_prompt if needed."""
    core_path = PROMPTS_DIR / "core"
    play_path = PROMPTS_DIR / "play_mode"
    if core_path.exists() and play_path.exists():
        return f"{load_prompt_file('core')}\n\n{load_prompt_file('play_mode')}"
    return load_prompt_file("system_prompt")


def compose_edit_system_prompt() -> str:
    """Compose core + edit_mode overlay."""
    return f"{load_prompt_file('core')}\n\n{load_prompt_file('edit_mode')}"


def compose_chat_system_prompt() -> str:
    """Compose core + chat_mode overlay."""
    return f"{load_prompt_file('core')}\n\n{load_prompt_file('chat_mode')}"


def compose_player_chat_system_prompt() -> str:
    """Compose core + play_mode + npc_chat for focused in-play NPC conversation."""
    return (
        f"{load_prompt_file('core')}\n\n"
        f"{load_prompt_file('play_mode')}\n\n"
        f"{load_prompt_file('npc_chat')}"
    )
