"""Phase 2a World Builder: propose → preview → validate → apply."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from world_sim.builder.apply import ApplyError, apply_seed_plan
from world_sim.builder.brief import load_guidance_brief
from world_sim.builder.core import BuilderSession
from world_sim.builder.plans import PLAN_STATUS_APPLIED, PLAN_STATUS_DRAFT, load_plan
from world_sim.builder.validation import validate_world
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.world_store import WorldStore
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_NPC,
    COLLECTION_ROOM,
    ChromaManager,
)
from world_sim.utils.logger import reset_logging_for_tests, setup_logging

CELLAR_LORE = (
    "The cellar is a cool stone room under the hallway, with packed earth "
    "corners and a single oil-stained shelf."
)
LANTERN_LORE = (
    "An oil lantern with a soot-dark chimney and a brass handle worn smooth."
)
GARDENER_DESC = "A quiet gardener in a patched coat, smelling faintly of soil."


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def builder(tmp_path: Path) -> BuilderSession:
    db = SqliteManager(tmp_path / "world.sqlite3")
    db.initialize_schema()
    world = WorldStore(db.connection)
    lore = ChromaManager(tmp_path / "chroma")
    return BuilderSession(world, lore, tmp_path, seed_starter=True)


def _add_cellar_lore(session: BuilderSession) -> None:
    session.lore.upsert_lore(COLLECTION_ROOM, "room:cellar", CELLAR_LORE)
    session.lore.upsert_lore(COLLECTION_ITEM, "item:oil_lantern", LANTERN_LORE)


def test_propose_preview_validate_apply(builder: BuilderSession) -> None:
    _add_cellar_lore(builder)
    plan = builder.propose_rooms(["room:cellar"])
    builder.propose_items(["item:oil_lantern"], place_in="cellar")
    builder.connect_rooms("hallway", "down", "cellar")
    builder.connect_rooms("cellar", "up", "hallway")

    assert plan.status == PLAN_STATUS_DRAFT
    preview = builder.preview()
    assert "cellar" in preview.lower()
    assert "draft until explicit apply" in preview.lower()
    assert builder.world.get_room("cellar") is None

    result = builder.validate()
    assert result.ok, result.format()

    applied = builder.apply()
    assert applied.status == PLAN_STATUS_APPLIED
    cellar = builder.world.get_room("cellar")
    assert cellar is not None
    assert cellar.lore_key == "room:cellar"
    assert builder.world.list_exits("hallway").get("down") == "cellar"
    assert builder.world.get_item_definition("oil_lantern") is not None
    assert any(
        item.item_definition_id == "oil_lantern"
        for item in builder.world.list_items_in_room("cellar")
    )
    assert "room:cellar" in builder.world.list_lore_keys("room", "cellar")


def test_propose_from_brief_draft_only(builder: BuilderSession, tmp_path: Path) -> None:
    _add_cellar_lore(builder)
    brief_path = tmp_path / "brief.yaml"
    brief_path.write_text(
        Path(__file__).resolve().parents[1].joinpath(
            "examples/seed-brief-cellar.yaml"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    plan = builder.propose_from_brief(brief_path)
    assert plan.status == PLAN_STATUS_DRAFT
    assert plan.brief_path
    assert builder.world.get_room("cellar") is None
    assert "oil_lantern" not in {
        item.item_id for item in builder.world.list_item_definitions()
    }

    preview = builder.preview()
    assert "Nothing has been written to SQLite" in preview
    result = builder.validate()
    assert result.ok, result.format()


def test_brief_constraint_validation(builder: BuilderSession, tmp_path: Path) -> None:
    _add_cellar_lore(builder)
    brief = {
        "goal": "Too many rooms",
        "constraints": {"max_rooms": 0, "max_items": 1, "max_npcs": 0},
        "propose": {
            "rooms": [{"lore_key": "room:cellar", "room_id": "cellar"}],
            "items": [],
            "npcs": [],
        },
        "must_link": [],
        "do_not": [],
    }
    path = tmp_path / "bad-brief.yaml"
    path.write_text(yaml.safe_dump(brief), encoding="utf-8")
    plan = builder.propose_from_brief(path)
    result = validate_world(builder.world, builder.lore, plan=plan)
    assert not result.ok
    assert any("max_rooms" in error for error in result.errors)


def test_brief_missing_lore_fail_closed(builder: BuilderSession, tmp_path: Path) -> None:
    brief = {
        "goal": "Invent a tower without lore",
        "constraints": {"max_rooms": 1},
        "propose": {
            "rooms": [{"lore_key": "room:clock_tower"}],
            "items": [],
            "npcs": [],
        },
        "must_link": [],
        "do_not": [],
    }
    path = tmp_path / "gap-brief.yaml"
    path.write_text(yaml.safe_dump(brief), encoding="utf-8")
    plan = builder.propose_from_brief(path)
    assert plan.gaps
    assert not plan.rooms
    result = validate_world(builder.world, builder.lore, plan=plan)
    assert not result.ok
    with pytest.raises(ApplyError):
        apply_seed_plan(builder.world, builder.lore, plan)


def test_broken_reference_detection(builder: BuilderSession) -> None:
    # Live world: SQLite FK blocks dangling exits; missing Chroma lore is the
    # cross-store break Builder must catch.
    builder.world.upsert_room("attic", "Attic", "room:attic_missing")
    live = validate_world(builder.world, builder.lore)
    assert not live.ok
    assert any("room:attic_missing" in error for error in live.errors)

    # Draft plan: exit to a room that exists neither in world nor plan.
    plan = builder.ensure_plan()
    from world_sim.builder.proposals import connect_rooms

    connect_rooms(plan, from_room_id="hallway", direction="up", to_room_id="ghost_loft")
    builder._persist(plan)
    planned = validate_world(builder.world, builder.lore, plan=plan)
    assert not planned.ok
    assert any("ghost_loft" in error for error in planned.errors)


def test_cross_store_lore_key_attachment(builder: BuilderSession) -> None:
    _add_cellar_lore(builder)
    builder.propose_rooms(["room:cellar"])
    builder.apply()
    assert builder.lore.get_lore(COLLECTION_ROOM, "room:cellar")
    refs = builder.world.list_lore_keys("room", "cellar")
    assert "room:cellar" in refs


def test_npc_mvp_profile_from_lore(builder: BuilderSession) -> None:
    builder.lore.upsert_lore(COLLECTION_NPC, "npc:gardener:description", GARDENER_DESC)
    plan = builder.propose_npcs(
        ["npc:gardener:description"],
        npc_id="gardener",
        name="Gardener",
        current_room_id="foyer",
    )
    assert plan.status == PLAN_STATUS_DRAFT
    result = builder.validate()
    assert result.ok, result.format()
    builder.apply()
    npc = builder.world.get_npc("gardener")
    assert npc is not None
    assert npc.name == "Gardener"
    assert "npc:gardener:description" in npc.npc_lore
    assert npc.current_room_id == "foyer"


def test_starter_world_still_valid(builder: BuilderSession) -> None:
    result = validate_world(builder.world, builder.lore)
    assert result.ok, result.format()
    assert builder.world.get_room("foyer") is not None


def test_upsert_lore_then_brief_apply(builder: BuilderSession, tmp_path: Path) -> None:
    builder.upsert_lore(
        "room:cellar",
        "The cellar is a cool stone room under the hallway.",
    )
    builder.upsert_lore(
        "item:oil_lantern",
        "An oil lantern with a soot-dark chimney.",
    )
    brief_path = tmp_path / "brief.yaml"
    brief_path.write_text(
        (Path(__file__).resolve().parents[1] / "examples/seed-brief-cellar.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    plan = builder.propose_from_brief(brief_path)
    assert not plan.gaps
    assert any(room.get("room_id") == "cellar" for room in plan.rooms)
    assert builder.validate().ok
    builder.apply()
    assert builder.world.get_room("cellar") is not None


def test_load_sample_brief() -> None:
    path = Path(__file__).resolve().parents[1] / "examples" / "seed-brief-cellar.yaml"
    brief = load_guidance_brief(path)
    assert brief["goal"]
    assert brief["constraints"]["max_rooms"] == 1
    assert brief["must_link"][0]["to"] == "cellar"


def test_apply_requires_validation(builder: BuilderSession) -> None:
    plan = builder.propose_rooms(["room:does_not_exist"])
    assert plan.gaps
    with pytest.raises(ApplyError):
        builder.apply()
    reloaded = load_plan(builder.data_dir, plan.plan_id)
    assert reloaded.status == PLAN_STATUS_DRAFT
