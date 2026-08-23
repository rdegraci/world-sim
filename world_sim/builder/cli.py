"""Command-line entry point for World Builder (`world-builder`)."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from world_sim.cli_input import prompt_line
from world_sim.builder.apply import ApplyError
from world_sim.builder.brief import BriefError
from world_sim.builder.core import BuilderSession
from world_sim.config import ConfigError, Settings, load_settings
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.utils.logger import get_logger, setup_logging

HELP_TEXT = """\
World Builder — structural construction for World-Sim (shared appdir/SQLite/Chroma).

Proposals are drafts until explicit apply. Exp-007 unsupervised apply is NOT enabled.

Commands:
  help
  list_lore [system|room|item|npc]
  discover_lore <query...>
  propose_discovered <rooms|items|npcs> <query...> [--in room_id]
  upsert_lore <lore_key> | <text...>
  list_plans
  open_plan <plan_id>
  propose_rooms_from_lore <lore_key> [lore_key...]
  propose_items_from_lore <lore_key> [lore_key...] [--in <room_id>]
  propose_npcs_from_lore <lore_key> [lore_key...] [--npc_id id] [--name name] [--in room]
  propose_from_brief <path>
  connect_rooms <from> <direction> <to>
  place_item <item_id> --in <room_id>
  place_npc <npc_id> --in <room_id>
  attach_room_lore <room_id> <lore_key>
  attach_item_lore <item_id> <lore_key>
  attach_npc_lore <npc_id> <lore_key>
  preview_seed_plan [plan_id]
  validate_world [--plan plan_id] [--world-only]
  apply_seed_plan [plan_id] [--yes]
  add_frontier_stub <from> <direction> --to <room_id> --lore <lore_key> [--name Name] [--return dir]
  list_frontier_stubs [pending|realized]
  quit | exit
"""


def run_builder(settings: Settings) -> int:
    logger = get_logger("builder")
    db = SqliteManager(settings.paths.sqlite_path)
    try:
        db.initialize_schema()
        world = WorldStore(db.connection)
        lore = ChromaManager(settings.paths.chroma_dir)
        session = BuilderSession(
            world,
            lore,
            settings.paths.data_dir,
            retrieval=settings.retrieval,
        )
        logger.info(
            "World Builder ready sqlite=%s chroma=%s plans=%s/builder/plans",
            settings.paths.sqlite_path,
            settings.paths.chroma_dir,
            settings.paths.data_dir,
        )
        print(
            "World Builder — shared World-Sim stores. "
            "Draft plans only until apply_seed_plan."
        )
        print("Type 'help' for commands.")
        return _repl(session, history_dir=settings.paths.data_dir)
    finally:
        db.close()


def _repl(session: BuilderSession, *, history_dir: Path | None = None) -> int:
    while True:
        try:
            raw = prompt_line("> ", kind="admin", history_dir=history_dir).strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("\nInterrupted.")
            return 130
        if not raw:
            continue
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            print(f"Parse error: {exc}")
            continue
        command = parts[0]
        args = parts[1:]
        if command in {"quit", "exit"}:
            return 0
        if command == "help":
            print(HELP_TEXT)
            continue
        try:
            message = dispatch(session, command, args, history_dir=history_dir)
        except (ApplyError, BriefError, FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}")
            continue
        if message:
            print(message)


def dispatch(
    session: BuilderSession,
    command: str,
    args: list[str],
    *,
    history_dir: Path | None = None,
) -> str:
    if command == "list_lore":
        collection = args[0] if args else None
        rows = session.list_lore(collection)
        if not rows:
            return "(no lore entries)"
        return "\n".join(f"{coll}\t{key}\t{preview}" for coll, key, preview in rows)

    if command == "discover_lore":
        if not args:
            raise ValueError("Usage: discover_lore <query...>")
        return session.discover_lore(" ".join(args))

    if command == "propose_discovered":
        if len(args) < 2:
            raise ValueError(
                "Usage: propose_discovered <rooms|items|npcs> <query...> [--in room_id]"
            )
        kind = args[0]
        rest = args[1:]
        place_in = None
        if "--in" in rest:
            idx = rest.index("--in")
            if idx + 1 >= len(rest):
                raise ValueError("--in requires a room_id")
            place_in = rest[idx + 1]
            rest = rest[:idx] + rest[idx + 2 :]
        if not rest:
            raise ValueError("Query text required after kind.")
        plan = session.propose_discovered(
            " ".join(rest),
            kind=kind,
            place_in=place_in,
        )
        return (
            f"Draft plan {plan.plan_id} updated from grounded retrieval "
            f"({len(plan.rooms)} rooms, {len(plan.items)} items, "
            f"{len(plan.npcs)} npcs). Gaps: {len(plan.gaps)}"
        )

    if command == "upsert_lore":
        # Prefer pipe form so free text is easy: upsert_lore room:cellar | The cellar...
        raw_line = " ".join(args)
        if "|" not in raw_line:
            raise ValueError(
                "Usage: upsert_lore <lore_key> | <text...> "
                "(optional: upsert_lore room <lore_key> | <text...>)"
            )
        key_part, text_part = raw_line.split("|", 1)
        key_tokens = shlex.split(key_part.strip()) if key_part.strip() else []
        if len(key_tokens) == 1:
            return session.upsert_lore(key_tokens[0], text_part)
        if len(key_tokens) == 2:
            return session.upsert_lore(
                key_tokens[1], text_part, collection=key_tokens[0]
            )
        raise ValueError("Usage: upsert_lore <lore_key> | <text...>")

    if command == "list_plans":
        ids = session.list_plans()
        current = session.current_plan_id
        if not ids:
            return "(no saved plans)"
        lines = []
        for plan_id in ids:
            mark = " *" if plan_id == current else ""
            lines.append(f"{plan_id}{mark}")
        return "\n".join(lines)

    if command == "open_plan":
        if not args:
            raise ValueError("Usage: open_plan <plan_id>")
        plan = session.open_plan(args[0])
        return f"Opened {plan.plan_id} (status={plan.status})"

    if command == "propose_rooms_from_lore":
        if not args:
            raise ValueError("Usage: propose_rooms_from_lore <lore_key>...")
        plan = session.propose_rooms(args)
        return f"Draft updated: {plan.plan_id}\n{session.preview()}"

    if command == "propose_items_from_lore":
        keys, options = _split_options(args)
        if not keys:
            raise ValueError("Usage: propose_items_from_lore <lore_key>... [--in room]")
        plan = session.propose_items(keys, place_in=options.get("in"))
        return f"Draft updated: {plan.plan_id}\n{session.preview()}"

    if command == "propose_npcs_from_lore":
        keys, options = _split_options(args)
        if not keys:
            raise ValueError(
                "Usage: propose_npcs_from_lore <lore_key>... "
                "[--npc_id id] [--name name] [--in room]"
            )
        plan = session.propose_npcs(
            keys,
            npc_id=options.get("npc_id"),
            name=options.get("name"),
            current_room_id=options.get("in"),
        )
        return f"Draft updated: {plan.plan_id}\n{session.preview()}"

    if command == "propose_from_brief":
        if not args:
            raise ValueError("Usage: propose_from_brief <path>")
        path = Path(args[0]).expanduser()
        plan = session.propose_from_brief(path)
        return (
            f"Draft seed plan created from brief (not applied): {plan.plan_id}\n"
            f"{session.preview()}"
        )

    if command == "connect_rooms":
        if len(args) != 3:
            raise ValueError("Usage: connect_rooms <from> <direction> <to>")
        plan = session.connect_rooms(args[0], args[1], args[2])
        return f"Draft updated: {plan.plan_id} (exit {args[0]} --{args[1]}--> {args[2]})"

    if command == "place_item":
        keys, options = _split_options(args)
        if len(keys) != 1 or "in" not in options:
            raise ValueError("Usage: place_item <item_id> --in <room_id>")
        plan = session.place_item(keys[0], options["in"])
        return f"Draft updated: {plan.plan_id}"

    if command == "place_npc":
        keys, options = _split_options(args)
        if len(keys) != 1 or "in" not in options:
            raise ValueError("Usage: place_npc <npc_id> --in <room_id>")
        plan = session.place_npc(keys[0], options["in"])
        return f"Draft updated: {plan.plan_id}"

    if command == "attach_room_lore":
        if len(args) != 2:
            raise ValueError("Usage: attach_room_lore <room_id> <lore_key>")
        plan = session.attach_room_lore(args[0], args[1])
        return f"Draft updated: {plan.plan_id}"

    if command == "attach_item_lore":
        if len(args) != 2:
            raise ValueError("Usage: attach_item_lore <item_id> <lore_key>")
        plan = session.attach_item_lore(args[0], args[1])
        return f"Draft updated: {plan.plan_id}"

    if command == "attach_npc_lore":
        if len(args) != 2:
            raise ValueError("Usage: attach_npc_lore <npc_id> <lore_key>")
        plan = session.attach_npc_lore(args[0], args[1])
        return f"Draft updated: {plan.plan_id}"

    if command == "preview_seed_plan":
        plan_id = args[0] if args else None
        return session.preview(plan_id)

    if command == "validate_world":
        plan_id = None
        include_plan = True
        tokens = list(args)
        while tokens:
            token = tokens.pop(0)
            if token == "--world-only":
                include_plan = False
            elif token == "--plan":
                if not tokens:
                    raise ValueError("--plan requires a plan_id")
                plan_id = tokens.pop(0)
            else:
                raise ValueError(f"Unknown validate_world option: {token}")
        result = session.validate(plan_id, include_plan=include_plan)
        return result.format()

    if command == "apply_seed_plan":
        tokens = list(args)
        yes = False
        plan_id = None
        while tokens:
            token = tokens.pop(0)
            if token in {"--yes", "-y"}:
                yes = True
            elif token.startswith("-"):
                raise ValueError(f"Unknown apply option: {token}")
            else:
                plan_id = token
        target = plan_id or session.current_plan_id
        if not target:
            raise ValueError("No plan to apply.")
        if not yes:
            print(session.preview(target))
            confirm = prompt_line(
                "Type 'apply' to commit this plan to SQLite: ",
                kind="admin",
                history_dir=history_dir,
            ).strip()
            if confirm != "apply":
                return "Apply cancelled. Plan remains a draft."
        plan = session.apply(target)
        return f"Applied {plan.plan_id}. World-Sim play can use the new structure."

    if command == "add_frontier_stub":
        keys, options = _split_options(args)
        if len(keys) != 2 or "to" not in options or "lore" not in options:
            raise ValueError(
                "Usage: add_frontier_stub <from> <direction> "
                "--to <room_id> --lore <lore_key> [--name Name] [--return dir]"
            )
        return session.add_frontier_stub(
            from_room_id=keys[0],
            direction=keys[1],
            target_room_id=options["to"],
            lore_key=options["lore"],
            target_name=options.get("name"),
            return_direction=options.get("return"),
        )

    if command == "list_frontier_stubs":
        status = args[0] if args else None
        if status and status not in {"pending", "realized"}:
            raise ValueError("Usage: list_frontier_stubs [pending|realized]")
        return session.list_frontier_stubs(status=status)

    raise ValueError(f"Unknown command: {command}. Type 'help'.")


def _split_options(args: list[str]) -> tuple[list[str], dict[str, str]]:
    positional: list[str] = []
    options: dict[str, str] = {}
    tokens = list(args)
    while tokens:
        token = tokens.pop(0)
        if token == "--in" and tokens:
            options["in"] = tokens.pop(0)
        elif token == "--npc_id" and tokens:
            options["npc_id"] = tokens.pop(0)
        elif token == "--name" and tokens:
            options["name"] = tokens.pop(0)
        elif token == "--to" and tokens:
            options["to"] = tokens.pop(0)
        elif token == "--lore" and tokens:
            options["lore"] = tokens.pop(0)
        elif token == "--return" and tokens:
            options["return"] = tokens.pop(0)
        elif token.startswith("--"):
            raise ValueError(f"Unknown option: {token}")
        else:
            positional.append(token)
    return positional, options


def main(argv: list[str] | None = None) -> None:
    """Bootstrap shared World-Sim config, then enter the Builder REPL."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"-h", "--help", "help"}:
        print(HELP_TEXT)
        raise SystemExit(0)

    try:
        setup_logging("INFO")
        settings = load_settings()
        setup_logging(settings.log_level)
    except ConfigError as exc:
        print(f"World Builder configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except OSError as exc:
        print(f"World Builder startup error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    logger = get_logger("builder")
    logger.info(
        "Starting World Builder (config_dir=%s data_dir=%s)",
        settings.paths.config_dir,
        settings.paths.data_dir,
    )
    raise SystemExit(run_builder(settings))


if __name__ == "__main__":
    main()
