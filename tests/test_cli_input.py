"""Tests for CLI input helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

import world_sim.cli_input as cli_input
from world_sim.cli_input import prompt_line


@pytest.fixture(autouse=True)
def _reset_cli_input_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_input, "_play_history_ready", False)
    monkeypatch.setattr(cli_input, "_play_history_path", None)
    monkeypatch.setattr(cli_input, "_admin_session", None)
    monkeypatch.setattr(cli_input, "_admin_session_key", None)
    monkeypatch.setattr(cli_input, "is_interactive", lambda: False)


def test_prompt_line_uses_plain_input_when_not_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_input(prompt: str) -> str:
        calls.append(prompt)
        return "look around"

    monkeypatch.setattr("builtins.input", fake_input)
    assert prompt_line("> ", kind="play") == "look around"
    assert prompt_line("edit> ", kind="admin") == "look around"
    assert calls == ["> ", "edit> "]


def test_prompt_line_play_readline_when_tty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli_input, "is_interactive", lambda: True)
    monkeypatch.setattr(cli_input, "_ensure_readline", lambda _history_dir: None)
    monkeypatch.setattr(cli_input, "_remember_play_line", lambda _line: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "go north")

    assert prompt_line("> ", kind="play", history_dir=tmp_path) == "go north"


def test_prompt_line_admin_uses_prompt_toolkit_when_tty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli_input, "is_interactive", lambda: True)

    class FakeSession:
        def prompt(self, prompt: str) -> str:
            assert prompt == "edit> "
            return "list_rooms"

    monkeypatch.setattr(
        cli_input,
        "_admin_prompt_session",
        lambda _history_dir: FakeSession(),
    )

    assert (
        prompt_line("edit> ", kind="admin", history_dir=tmp_path) == "list_rooms"
    )
