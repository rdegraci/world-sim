"""Command-line entry point for World-Sim."""

from __future__ import annotations

import sys

from world_sim.config import ConfigError, load_settings
from world_sim.server.session_server import run_session
from world_sim.utils.logger import get_logger, setup_logging


def main(argv: list[str] | None = None) -> None:
    """Bootstrap config, then start the local World-Sim session loop."""
    del argv  # Reserved for future CLI flags.

    try:
        # Configure a temporary INFO logger so bootstrap messages are visible
        # before settings (and the configured log level) are known.
        setup_logging("INFO")
        settings = load_settings()
        setup_logging(settings.log_level)
    except ConfigError as exc:
        print(f"World-Sim configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except OSError as exc:
        print(f"World-Sim startup error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    logger = get_logger("cli")
    logger.info(
        "Starting local session (provider=%s, config_dir=%s)",
        settings.provider,
        settings.paths.config_dir,
    )
    raise SystemExit(run_session())


if __name__ == "__main__":
    main()
