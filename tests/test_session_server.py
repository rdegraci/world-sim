"""Tests for the local session shell."""

from __future__ import annotations

from world_sim.server.session_server import run_session


def test_quit_exits_cleanly() -> None:
    outputs: list[str] = []
    inputs = iter(["quit"])

    code = run_session(input_fn=lambda _: next(inputs), output_fn=outputs.append)

    assert code == 0
    assert any("Goodbye." in line for line in outputs)


def test_help_then_exit() -> None:
    outputs: list[str] = []
    inputs = iter(["help", "exit"])

    code = run_session(input_fn=lambda _: next(inputs), output_fn=outputs.append)

    assert code == 0
    assert any("Commands:" in line for line in outputs)


def test_unknown_command_is_acknowledged() -> None:
    outputs: list[str] = []
    inputs = iter(["look around", "quit"])

    code = run_session(input_fn=lambda _: next(inputs), output_fn=outputs.append)

    assert code == 0
    assert any("not implemented yet" in line for line in outputs)
