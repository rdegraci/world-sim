"""Command-line entry point for World-Sim."""

from __future__ import annotations

import sys

from world_sim.auth.onboarding import AuthError, authenticate
from world_sim.config import ConfigError, Settings, load_settings
from world_sim.authority import WorldAuthority
from world_sim.db.draft_store import DraftStore
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.factory import create_llm_adapter
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.lore.seed import (
    DEFAULT_CHAT_NPC_ID,
    ensure_player_starting_room,
    seed_starter_world,
)
from world_sim.orchestrator.chat import ChatOrchestrator
from world_sim.orchestrator.edit import EditOrchestrator
from world_sim.orchestrator.play import PlayOrchestrator
from world_sim.server.session_server import run_session
from world_sim.utils.logger import get_logger, setup_logging


def run_app(settings: Settings) -> int:
    """Initialize storage, seed world, authenticate, and enter play/edit/chat."""
    logger = get_logger("cli")
    db = SqliteManager(settings.paths.sqlite_path)
    try:
        db.initialize_schema()
        store = UserStore(db.connection)
        world_store = WorldStore(db.connection)
        authority = WorldAuthority(world_store)
        drafts = DraftStore(db.connection)
        lore = ChromaManager(settings.paths.chroma_dir)
        seeded = seed_starter_world(world_store, lore)
        logger.info(
            "SQLite ready at %s; starter world seeded=%s",
            settings.paths.sqlite_path,
            seeded,
        )

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

        ensure_player_starting_room(world_store, auth.player_character.id)
        try:
            llm = create_llm_adapter(settings)
        except ConfigError as exc:
            print(f"World-Sim configuration error: {exc}", file=sys.stderr)
            return 1

        chat_npc_id = str(
            settings.raw_config.get("chat_npc_id")
            or world_store.get_meta("chat_npc_id")
            or DEFAULT_CHAT_NPC_ID
        )
        play = PlayOrchestrator(
            world=authority,
            lore=lore,
            llm=llm,
            user_store=store,
            auth=auth,
            expansion=settings.world,
        )
        edit = EditOrchestrator(
            world=world_store,
            lore=lore,
            drafts=drafts,
            llm=llm,
            auth=auth,
        )
        chat = ChatOrchestrator(
            world=world_store,
            lore=lore,
            llm=llm,
            user_store=store,
            auth=auth,
            npc_id=chat_npc_id,
        )

        logger.info(
            "Authenticated username=%s role=%s session_id=%s room=%s chat_npc=%s",
            auth.user.username,
            auth.user.role,
            auth.session.id,
            world_store.get_player_room_id(auth.player_character.id),
            chat_npc_id,
        )
        return run_session(auth=auth, store=store, play=play, edit=edit, chat=chat)
    finally:
        db.close()


def main(argv: list[str] | None = None) -> None:
    """Bootstrap config, then start the local World-Sim session loop."""
    del argv  # Reserved for future CLI flags.

    try:
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
