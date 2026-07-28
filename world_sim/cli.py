"""Command-line entry point for World-Sim."""

from __future__ import annotations

import sys

from world_sim.server.session_server import main as run_session_main


def main() -> None:
    """Start the local World-Sim session loop."""
    raise SystemExit(run_session_main())


if __name__ == "__main__":
    main()
