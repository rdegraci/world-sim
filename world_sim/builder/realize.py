"""Realize prepared frontier stubs via Builder propose/validate/apply."""

from __future__ import annotations

from world_sim.authority import WorldAuthority
from world_sim.builder.apply import ApplyError, apply_seed_plan
from world_sim.builder.linking import lore_exists
from world_sim.builder.plans import create_empty_plan
from world_sim.builder.proposals import connect_rooms
from world_sim.builder.validation import validate_world
from world_sim.config import WorldExpansionSettings
from world_sim.db.world_store import FrontierStub, WorldStore
from world_sim.lore.chroma_manager import ChromaManager
from world_sim.utils.logger import get_logger


class RealizeError(RuntimeError):
    """Raised when a frontier stub cannot be realized."""


def _as_store(world: WorldAuthority | WorldStore) -> WorldStore:
    if isinstance(world, WorldAuthority):
        return world.store
    return world


def _emit_room_realized(
    world: WorldAuthority | WorldStore,
    *,
    stub_id: str,
    room_id: str,
    lore_key: str,
    from_room_id: str | None = None,
    direction: str | None = None,
    already_existed: bool = False,
) -> None:
    if isinstance(world, WorldAuthority):
        world.record_room_realized(
            stub_id=stub_id,
            room_id=room_id,
            lore_key=lore_key,
            from_room_id=from_room_id,
            direction=direction,
            already_existed=already_existed,
        )
        return
    payload: dict = {
        "stub_id": stub_id,
        "room_id": room_id,
        "lore_key": lore_key,
        "already_existed": already_existed,
    }
    if from_room_id is not None:
        payload["from_room_id"] = from_room_id
    if direction is not None:
        payload["direction"] = direction
    world.append_runtime_event("room_realized", payload)


def realize_adjacent(
    world: WorldAuthority | WorldStore,
    lore: ChromaManager,
    stub: FrontierStub,
    *,
    settings: WorldExpansionSettings,
    realized_this_session: int = 0,
) -> FrontierStub:
    """Realize one pending stub into durable SQLite structure.

    Reuses Builder seed-plan validate/apply. Play narration must not call this
    except through the authoritative movement/realize path.
    """
    store = _as_store(world)
    if not settings.dynamic_expansion:
        raise RealizeError(
            "Dynamic expansion is off. Crossing unrealized stubs is blocked."
        )
    if settings.require_brief_or_stub and stub.status != "pending":
        raise RealizeError(f"Stub '{stub.stub_id}' is not pending.")
    if stub.status != "pending":
        raise RealizeError(f"Stub '{stub.stub_id}' status is '{stub.status}'.")

    if settings.max_new_rooms_per_session >= 0:
        if realized_this_session >= settings.max_new_rooms_per_session:
            raise RealizeError(
                "Session room-realization cap reached "
                f"({settings.max_new_rooms_per_session})."
            )

    if store.get_room(stub.from_room_id) is None:
        raise RealizeError(f"From-room '{stub.from_room_id}' is missing.")

    if not lore_exists(lore, stub.lore_key):
        raise RealizeError(
            f"Fail closed: approved lore '{stub.lore_key}' is missing in Chroma. "
            "Cannot realize contradicting or invented structure."
        )

    existing = store.get_room(stub.target_room_id)
    if existing is not None:
        # Campaign identity: room already durable — wire exits if needed, mark realized.
        store.upsert_exit(stub.from_room_id, stub.direction, stub.target_room_id)
        if stub.return_direction:
            store.upsert_exit(
                stub.target_room_id,
                stub.return_direction,
                stub.from_room_id,
            )
        store.mark_stub_realized(stub.stub_id)
        _emit_room_realized(
            world,
            stub_id=stub.stub_id,
            room_id=stub.target_room_id,
            lore_key=stub.lore_key,
            from_room_id=stub.from_room_id,
            direction=stub.direction,
            already_existed=True,
        )
        refreshed = store.get_frontier_stub(stub.stub_id)
        if refreshed is None:
            raise RealizeError("Stub missing after mark.")
        return refreshed

    plan = create_empty_plan()
    plan.notes.append(
        f"Frontier realization from stub {stub.stub_id} "
        f"({stub.from_room_id} --{stub.direction}--> {stub.target_room_id})."
    )
    plan.rooms.append(
        {
            "room_id": stub.target_room_id,
            "name": stub.target_name,
            "lore_key": stub.lore_key,
            "action": "create",
        }
    )
    plan.attachments.append(
        {
            "entity_kind": "room",
            "entity_id": stub.target_room_id,
            "lore_key": stub.lore_key,
        }
    )
    connect_rooms(
        plan,
        from_room_id=stub.from_room_id,
        direction=stub.direction,
        to_room_id=stub.target_room_id,
    )
    if stub.return_direction:
        connect_rooms(
            plan,
            from_room_id=stub.target_room_id,
            direction=stub.return_direction,
            to_room_id=stub.from_room_id,
        )

    result = validate_world(store, lore, plan=plan)
    if not result.ok:
        joined = "; ".join(result.errors)
        raise RealizeError(f"Fail closed on lore/structure validation: {joined}")

    try:
        apply_seed_plan(store, lore, plan)
    except ApplyError as exc:
        raise RealizeError(f"Fail closed on apply: {exc}") from exc

    store.mark_stub_realized(stub.stub_id)
    _emit_room_realized(
        world,
        stub_id=stub.stub_id,
        room_id=stub.target_room_id,
        lore_key=stub.lore_key,
        from_room_id=stub.from_room_id,
        direction=stub.direction,
        already_existed=False,
    )
    get_logger("frontier").info(
        "Realized stub=%s room=%s lore=%s",
        stub.stub_id,
        stub.target_room_id,
        stub.lore_key,
    )
    refreshed = store.get_frontier_stub(stub.stub_id)
    if refreshed is None:
        raise RealizeError("Stub missing after realize.")
    return refreshed
