"""Tests for Slice 1 config bootstrap and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.config import (
    ConfigError,
    bootstrap_directories,
    load_settings,
    resolve_paths,
    validate_and_build_settings,
)
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    yield
    reset_logging_for_tests()


def _write_env(path: Path, *, grok_api_key: str = "test-grok-key") -> None:
    path.write_text(f"GROK_API_KEY={grok_api_key}\n", encoding="utf-8")


def test_resolve_paths_separates_config_and_data_when_same(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    paths = resolve_paths(config_dir=shared, data_dir=shared)

    assert paths.config_dir == shared
    assert paths.data_dir == shared / "data"
    assert paths.env_path == shared / ".env"
    assert paths.config_path == shared / "config.yaml"
    assert paths.sqlite_path == shared / "data" / "world_sim.sqlite3"
    assert paths.chroma_dir == shared / "data" / "chroma"


def test_resolve_paths_keeps_distinct_dirs(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    paths = resolve_paths(config_dir=config_dir, data_dir=data_dir)

    assert paths.config_dir == config_dir
    assert paths.data_dir == data_dir
    assert paths.sqlite_path == data_dir / "world_sim.sqlite3"


def test_first_run_bootstrap_creates_files(tmp_path: Path) -> None:
    setup_logging("INFO")
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    paths = resolve_paths(config_dir=config_dir, data_dir=data_dir)

    created = bootstrap_directories(paths)

    assert created["config_dir"] is True
    assert created["data_dir"] is True
    assert created["config_yaml"] is True
    assert created["env_template"] is True
    assert created["sqlite"] is True
    assert created["chroma_dir"] is True
    assert paths.config_path.is_file()
    assert paths.env_path.is_file()
    assert paths.sqlite_path.is_file()
    assert paths.chroma_dir.is_dir()


def test_second_run_reuses_bootstrapped_files(tmp_path: Path) -> None:
    setup_logging("INFO")
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    paths = resolve_paths(config_dir=config_dir, data_dir=data_dir)

    first = bootstrap_directories(paths)
    assert any(first.values())

    original_config = paths.config_path.read_text(encoding="utf-8")
    original_env = paths.env_path.read_text(encoding="utf-8")
    _write_env(paths.env_path, grok_api_key="kept-key")

    second = bootstrap_directories(paths)
    assert not any(second.values())
    assert paths.config_path.read_text(encoding="utf-8") == original_config
    assert "kept-key" in paths.env_path.read_text(encoding="utf-8")
    # Template was replaced by the test write; ensure bootstrap did not clobber it.
    assert paths.env_path.read_text(encoding="utf-8") != original_env


def test_load_settings_succeeds_with_grok_key(tmp_path: Path) -> None:
    setup_logging("INFO")
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    paths = resolve_paths(config_dir=config_dir, data_dir=data_dir)
    bootstrap_directories(paths)
    _write_env(paths.env_path)

    settings = load_settings(paths=paths)

    assert settings.provider == "grok"
    assert settings.grok_api_key == "test-grok-key"
    assert settings.log_level == "INFO"
    assert settings.paths.sqlite_path.is_file()
    assert settings.paths.chroma_dir.is_dir()


def test_missing_grok_key_fails_clearly(tmp_path: Path) -> None:
    setup_logging("INFO")
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    paths = resolve_paths(config_dir=config_dir, data_dir=data_dir)
    bootstrap_directories(paths)
    # Leave the generated empty GROK_API_KEY= template as-is.

    with pytest.raises(ConfigError, match="GROK_API_KEY") as exc_info:
        load_settings(paths=paths)

    message = str(exc_info.value)
    assert str(paths.env_path) in message
    assert "non-empty" in message.lower() or "set GROK_API_KEY" in message


def test_invalid_yaml_fails_clearly(tmp_path: Path) -> None:
    setup_logging("INFO")
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    paths = resolve_paths(config_dir=config_dir, data_dir=data_dir)
    bootstrap_directories(paths)
    paths.config_path.write_text("provider: [unterminated\n", encoding="utf-8")
    _write_env(paths.env_path)

    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_settings(paths=paths)


def test_validate_requires_grok_for_default_provider(tmp_path: Path) -> None:
    paths = resolve_paths(config_dir=tmp_path / "c", data_dir=tmp_path / "d")
    with pytest.raises(ConfigError, match="GROK_API_KEY"):
        validate_and_build_settings(paths, {"provider": "grok"}, {"GROK_API_KEY": ""})
