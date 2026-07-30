"""App path resolution, config loading, and first-run bootstrap."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from platformdirs import user_config_dir, user_data_dir

from world_sim.utils.logger import get_logger

APP_NAME = "world-sim"
DEFAULT_PROVIDER = "grok"
DEFAULT_LOG_LEVEL = "INFO"

DEFAULT_CONFIG_YAML = """\
# World-Sim runtime settings
provider: grok
grok_model: grok-4.5
# openai_model: gpt-4o-mini
# anthropic_model: claude-sonnet-4-20250514
chat_npc_id: mrs_hale
logging:
  level: INFO
"""

DEFAULT_ENV_TEMPLATE = """\
# World-Sim secrets. Fill in required values before starting.
GROK_API_KEY=
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
# ADMIN_PASSWORD=
"""


class ConfigError(Exception):
    """Raised when configuration or secrets cannot be loaded or validated."""


@dataclass(frozen=True)
class AppPaths:
    """Resolved filesystem locations for config and runtime data."""

    config_dir: Path
    data_dir: Path
    env_path: Path
    config_path: Path
    sqlite_path: Path
    chroma_dir: Path


@dataclass(frozen=True)
class Settings:
    """Effective runtime settings after bootstrap and validation."""

    paths: AppPaths
    provider: str
    log_level: str
    grok_api_key: str
    openai_api_key: str | None
    anthropic_api_key: str | None
    admin_password: str | None
    raw_config: dict[str, Any]


def resolve_paths(
    *,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
) -> AppPaths:
    """Resolve platformdirs locations, keeping config and data distinct."""
    resolved_config = Path(
        config_dir
        if config_dir is not None
        else user_config_dir(APP_NAME, appauthor=False)
    )
    resolved_data = Path(
        data_dir if data_dir is not None else user_data_dir(APP_NAME, appauthor=False)
    )

    # On some platforms (notably macOS) config and data dirs can resolve to the
    # same path. Keep runtime storage under a data/ subdirectory in that case.
    if resolved_data.resolve() == resolved_config.resolve():
        resolved_data = resolved_config / "data"

    return AppPaths(
        config_dir=resolved_config,
        data_dir=resolved_data,
        env_path=resolved_config / ".env",
        config_path=resolved_config / "config.yaml",
        sqlite_path=resolved_data / "world_sim.sqlite3",
        chroma_dir=resolved_data / "chroma",
    )


def _write_text_if_missing(path: Path, contents: str) -> bool:
    if path.exists():
        return False
    path.write_text(contents, encoding="utf-8")
    return True


def _ensure_sqlite_file(path: Path) -> bool:
    """Create an empty SQLite database file if missing. Returns True if created."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.close()
    return True


def bootstrap_directories(paths: AppPaths) -> dict[str, bool]:
    """Create app directories and first-run files. Returns what was created."""
    created = {
        "config_dir": not paths.config_dir.exists(),
        "data_dir": not paths.data_dir.exists(),
        "config_yaml": False,
        "env_template": False,
        "sqlite": False,
        "chroma_dir": not paths.chroma_dir.exists(),
    }

    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    created["config_yaml"] = _write_text_if_missing(
        paths.config_path, DEFAULT_CONFIG_YAML
    )
    created["env_template"] = _write_text_if_missing(
        paths.env_path, DEFAULT_ENV_TEMPLATE
    )
    created["sqlite"] = _ensure_sqlite_file(paths.sqlite_path)
    paths.chroma_dir.mkdir(parents=True, exist_ok=True)

    return created


def _load_yaml_config(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read config file at {path}: {exc}") from exc

    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ConfigError(
            f"Invalid config at {path}: expected a mapping at the top level."
        )
    return loaded


def _load_env(path: Path) -> dict[str, str | None]:
    if not path.exists():
        raise ConfigError(
            f"Missing secrets file at {path}. "
            "Create it and set GROK_API_KEY (required for Slice 1)."
        )
    values = dotenv_values(path)
    return {key: value for key, value in values.items()}


def _nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def validate_and_build_settings(
    paths: AppPaths,
    raw_config: dict[str, Any],
    env_values: dict[str, str | None],
) -> Settings:
    """Validate loaded config/secrets and build Settings."""
    provider = str(raw_config.get("provider", DEFAULT_PROVIDER)).strip().lower()
    if not provider:
        provider = DEFAULT_PROVIDER

    logging_section = raw_config.get("logging", {})
    if logging_section is None:
        logging_section = {}
    if not isinstance(logging_section, dict):
        raise ConfigError("config.yaml key 'logging' must be a mapping.")

    log_level = str(logging_section.get("level", DEFAULT_LOG_LEVEL)).strip().upper()
    if not log_level:
        log_level = DEFAULT_LOG_LEVEL

    grok_api_key = _nonempty(env_values.get("GROK_API_KEY"))
    openai_api_key = _nonempty(env_values.get("OPENAI_API_KEY"))
    anthropic_api_key = _nonempty(env_values.get("ANTHROPIC_API_KEY"))
    admin_password = _nonempty(env_values.get("ADMIN_PASSWORD"))

    if provider == "grok" and not grok_api_key:
        raise ConfigError(
            f"Missing required secret GROK_API_KEY in {paths.env_path}. "
            "Set GROK_API_KEY to a non-empty value and restart."
        )
    if provider == "openai" and not openai_api_key:
        raise ConfigError(
            f"Missing required secret OPENAI_API_KEY in {paths.env_path}. "
            "Set OPENAI_API_KEY to a non-empty value and restart."
        )
    if provider in {"anthropic", "claude"} and not anthropic_api_key:
        raise ConfigError(
            f"Missing required secret ANTHROPIC_API_KEY in {paths.env_path}. "
            "Set ANTHROPIC_API_KEY to a non-empty value and restart."
        )
    if provider not in {"grok", "openai", "anthropic", "claude"}:
        raise ConfigError(
            f"Unknown provider '{provider}'. Supported: grok, openai, anthropic."
        )

    return Settings(
        paths=paths,
        provider=provider,
        log_level=log_level,
        grok_api_key=grok_api_key or "",
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        admin_password=admin_password,
        raw_config=raw_config,
    )


def load_settings(
    *,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
    paths: AppPaths | None = None,
) -> Settings:
    """Bootstrap directories, load config/secrets, and return validated settings."""
    logger = get_logger("config")
    resolved = paths or resolve_paths(config_dir=config_dir, data_dir=data_dir)
    created = bootstrap_directories(resolved)

    if any(created.values()):
        logger.info(
            "First-run bootstrap created: %s",
            ", ".join(name for name, was_created in created.items() if was_created),
        )
    else:
        logger.info("Using existing app directories at config=%s data=%s",
                    resolved.config_dir, resolved.data_dir)

    raw_config = _load_yaml_config(resolved.config_path)
    env_values = _load_env(resolved.env_path)
    settings = validate_and_build_settings(resolved, raw_config, env_values)

    logger.info(
        "Loaded settings provider=%s config=%s sqlite=%s chroma=%s",
        settings.provider,
        resolved.config_path,
        resolved.sqlite_path,
        resolved.chroma_dir,
    )
    return settings
