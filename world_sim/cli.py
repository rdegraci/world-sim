"""Command-line entry point for World-Sim."""

from __future__ import annotations

import sys

from world_sim.auth.onboarding import AuthError, authenticate
from world_sim.config import ConfigError, Settings, load_settings
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.server.session_server import run_session
from world_sim.utils.logger import get_logger, setup_logging


def run_app(settings: Settings) -> int:
    """Initialize SQLite, authenticate, and enter the local session loop."""
    logger = get_logger("cli")
    db = SqliteManager(settings.paths.sqlite_path)
    try:
        db.initialize_schema()
        store = UserStore(db.connection)
        logger.info("SQLite schema ready at %s", settings.paths.sqlite_path)

        try:
            auth = authenticate(store, admin_password=settings.admin_password)
        except AuthError as exc:
            print(f"World-Sim authentication error: {exc}", file=sys.stderr)
            return 1
        except EOFError:
            print("\nAuthentication cancelled.", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nAuthentication interrupted.", file=sys.stderr)
            return 130

        logger.info(
            "Authenticated username=%s role=%s session_id=%s",
            auth.user.username,
            auth.user.role,
            auth.session.id,
        )
        return run_session(auth=auth, store=store)
    finally:
        db.close()


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
    raise SystemExit(run_app(settings))


if __name__ == "__main__":
    main()
