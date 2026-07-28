"""Tests for CLI startup wiring (Slice 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim import cli
from world_sim import config as config_mod
from world_sim.config import bootstrap_directories, resolve_paths
from world_sim.utils.logger import reset_logging_for_tests


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    yield
    reset_logging_for_tests()


def test_main_exits_with_config_error_when_grok_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = resolve_paths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    bootstrap_directories(paths)

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: config_mod.load_settings(paths=paths),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "configuration error" in err.lower()
    assert "GROK_API_KEY" in err


def test_main_starts_session_after_successful_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = resolve_paths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    bootstrap_directories(paths)
    paths.env_path.write_text("GROK_API_KEY=test-key\n", encoding="utf-8")

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: config_mod.load_settings(paths=paths),
    )
    monkeypatch.setattr(cli, "run_session", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
