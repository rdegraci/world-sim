"""Realize prepared frontier stubs via Builder propose/validate/apply."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
    emit_event: Callable[..., Any] | None = None,
) -> None:
    """Persist/fan-out room_realized. Prefer ``emit_event`` when already under the gate."""
    payload: dict[str, Any] = {
        "stub_id": stub_id,
        "room_id": room_id,
        "lore_key": lore_key,
        "already_existed": already_existed,
    }
    if from_room_id is not None:
        payload["from_room_id"] = from_room_id
    if direction is not None:
        payload["direction"] = direction
    room_ids = tuple(r for r in (room_id, from_room_id) if isinstance(r, str))

    if emit_event is not None:
        emit_event(payload, room_ids=room_ids)
        return
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
    world.append_runtime_event("room_realized", payload)


def apply_realize_adjacent(
    store: WorldStore,
    lore: ChromaManager,
    stub: FrontierStub,
    *,
    settings: WorldExpansionSettings,
    realized_this_session: int = 0,
    world: WorldAuthority | WorldStore | None = None,
    emit_event: Callable[..., Any] | None = None,
) -> FrontierStub:
    """Apply stub realization to SQLite. Caller must hold the authority serial gate when contested.

    Idempotent if the stub is already ``realized`` (second waiter after a winner).
    """
    event_target: WorldAuthority | WorldStore = world if world is not None else store

    if not settings.dynamic_expansion:
        raise RealizeError(
            "Dynamic expansion is off. Crossing unrealized stubs is blocked."
        )

    current = store.get_frontier_stub(stub.stub_id)
    if current is None:
        raise RealizeError(f"Stub '{stub.stub_id}' is missing.")
    if current.status == "realized":
        return current
    if settings.require_brief_or_stub and current.status != "pending":
        raise RealizeError(f"Stub '{current.stub_id}' is not pending.")
    if current.status != "pending":
        raise RealizeError(f"Stub '{current.stub_id}' status is '{current.status}'.")

    if settings.max_new_rooms_per_session >= 0:
        if realized_this_session >= settings.max_new_rooms_per_session:
            raise RealizeError(
                "Session room-realization cap reached "
                f"({settings.max_new_rooms_per_session})."
            )

    if store.get_room(current.from_room_id) is None:
        raise RealizeError(f"From-room '{current.from_room_id}' is missing.")

    if not lore_exists(lore, current.lore_key):
        raise RealizeError(
            f"Fail closed: approved lore '{current.lore_key}' is missing in Chroma. "
            "Cannot realize contradicting or invented structure."
        )

    existing = store.get_room(current.target_room_id)
    if existing is not None:
        # Campaign identity: room already durable — wire exits if needed, mark realized.
        store.upsert_exit(current.from_room_id, current.direction, current.target_room_id)
        if current.return_direction:
            store.upsert_exit(
                current.target_room_id,
                current.return_direction,
                current.from_room_id,
            )
        store.mark_stub_realized(current.stub_id)
        _emit_room_realized(
            event_target,
            stub_id=current.stub_id,
            room_id=current.target_room_id,
            lore_key=current.lore_key,
            from_room_id=current.from_room_id,
            direction=current.direction,
            already_existed=True,
            emit_event=emit_event,
        )
        refreshed = store.get_frontier_stub(current.stub_id)
        if refreshed is None:
            raise RealizeError("Stub missing after mark.")
        return refreshed

    plan = create_empty_plan()
    plan.notes.append(
        f"Frontier realization from stub {current.stub_id} "
        f"({current.from_room_id} --{current.direction}--> {current.target_room_id})."
    )
    plan.rooms.append(
        {
            "room_id": current.target_room_id,
            "name": current.target_name,
            "lore_key": current.lore_key,
            "action": "create",
        }
    )
    plan.attachments.append(
        {
            "entity_kind": "room",
            "entity_id": current.target_room_id,
            "lore_key": current.lore_key,
        }
    )
    connect_rooms(
        plan,
        from_room_id=current.from_room_id,
        direction=current.direction,
        to_room_id=current.target_room_id,
    )
    if current.return_direction:
        connect_rooms(
            plan,
            from_room_id=current.target_room_id,
            direction=current.return_direction,
            to_room_id=current.from_room_id,
        )

    result = validate_world(store, lore, plan=plan)
    if not result.ok:
        joined = "; ".join(result.errors)
        raise RealizeError(f"Fail closed on lore/structure validation: {joined}")

    try:
        apply_seed_plan(store, lore, plan)
    except ApplyError as exc:
        raise RealizeError(f"Fail closed on apply: {exc}") from exc

    store.mark_stub_realized(current.stub_id)
    _emit_room_realized(
        event_target,
        stub_id=current.stub_id,
        room_id=current.target_room_id,
        lore_key=current.lore_key,
        from_room_id=current.from_room_id,
        direction=current.direction,
        already_existed=False,
        emit_event=emit_event,
    )
    get_logger("frontier").info(
        "Realized stub=%s room=%s lore=%s",
        current.stub_id,
        current.target_room_id,
        current.lore_key,
    )
    refreshed = store.get_frontier_stub(current.stub_id)
    if refreshed is None:
        raise RealizeError("Stub missing after realize.")
    return refreshed


def realize_adjacent(
    world: WorldAuthority | WorldStore,
    lore: ChromaManager,
    stub: FrontierStub,
    *,
    settings: WorldExpansionSettings,
    realized_this_session: int = 0,
    actor_player_character_id: int | None = None,
) -> FrontierStub:
    """Realize one pending stub into durable SQLite structure.

    When ``world`` is a :class:`WorldAuthority`, structure writes run under the
    serial mutation gate (contested-safe). Builder/offline callers may pass a
    bare :class:`WorldStore` (single-writer assumed).
    """
    if isinstance(world, WorldAuthority):
        return world.realize_frontier_stub(
            lore,
            stub,
            settings=settings,
            realized_this_session=realized_this_session,
            actor_player_character_id=actor_player_character_id,
        )
    return apply_realize_adjacent(
        world,
        lore,
        stub,
        settings=settings,
        realized_this_session=realized_this_session,
        world=world,
    )
