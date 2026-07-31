"""Entrypoint: ``world-sim-serve`` — multi-session HTTP + WebSocket host."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from world_sim.authority import WorldAuthority
from world_sim.config import ConfigError, load_settings
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.factory import create_llm_adapter
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.lore.seed import seed_starter_world
from world_sim.server.app import WorldRuntime, create_app
from world_sim.server.hub import SessionHub
from world_sim.utils.logger import get_logger, setup_logging


def build_runtime():
    settings = load_settings()
    setup_logging(settings.log_level)
    db = SqliteManager(settings.paths.sqlite_path)
    db.initialize_schema()
    user_store = UserStore(db.connection)
    world_store = WorldStore(db.connection)
    authority = WorldAuthority(world_store, memory=settings.memory)
    lore = ChromaManager(settings.paths.chroma_dir)
    seed_starter_world(world_store, lore)
    llm = create_llm_adapter(settings)
    hub = SessionHub(authority=authority)
    runtime = WorldRuntime(
        settings=settings,
        user_store=user_store,
        authority=authority,
        lore=lore,
        llm=llm,
        hub=hub,
    )
    # Keep db open for process lifetime.
    runtime._db = db  # noqa: SLF001
    return runtime


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "World-Sim Phase 3b multi-session server "
            "(HTTP + WebSocket + thin web). "
            "Use TLS termination (WSS) in real deploys."
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    try:
        runtime = build_runtime()
    except ConfigError as exc:
        print(f"World-Sim configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    app = create_app(runtime)
    logger = get_logger("serve")
    logger.info(
        "Serving thin web at http://%s:%s/ (WS /ws?token=…). "
        "CLI may use the same SQLite world via world-sim.",
        args.host,
        args.port,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
