"""Authoritative schematic map payloads for thin web / CLIENT-MAP.md."""

from __future__ import annotations

from collections import deque
from typing import Any

from world_sim.authority import WorldAuthority
from world_sim.db.world_store import WorldStore

_DIR_DELTA = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
    "up": (0, -1),
    "down": (0, 1),
}


def _seen_rooms(store: WorldStore, player_character_id: int) -> set[str]:
    seen: set[str] = set()
    for room in store.list_rooms():
        full_seen, _ = store.get_room_presentation(player_character_id, room.room_id)
        if full_seen:
            seen.add(room.room_id)
    current = store.get_player_room_id(player_character_id)
    if current:
        seen.add(current)
    return seen


def _layout_positions(store: WorldStore, origin: str | None) -> dict[str, tuple[int, int]]:
    """BFS grid layout from origin using cardinal exits."""
    rooms = {r.room_id: r for r in store.list_rooms()}
    if not rooms:
        return {}
    start = origin if origin in rooms else next(iter(rooms))
    positions: dict[str, tuple[int, int]] = {start: (0, 0)}
    queue: deque[str] = deque([start])
    occupied = {(0, 0)}
    while queue:
        room_id = queue.popleft()
        x, y = positions[room_id]
        for direction, target in store.list_exits(room_id).items():
            if target in positions or target not in rooms:
                continue
            dx, dy = _DIR_DELTA.get(direction, (1, 0))
            nx, ny = x + dx, y + dy
            # Resolve collisions by shifting east.
            while (nx, ny) in occupied:
                nx += 1
            positions[target] = (nx, ny)
            occupied.add((nx, ny))
            queue.append(target)
    # Place any disconnected rooms to the side.
    max_x = max((p[0] for p in positions.values()), default=0)
    for room_id in rooms:
        if room_id not in positions:
            max_x += 2
            positions[room_id] = (max_x, 0)
    return positions


def _graph_distance(
    store: WorldStore,
    start: str,
    *,
    max_depth: int = 8,
) -> dict[str, int]:
    dist = {start: 0}
    queue: deque[str] = deque([start])
    while queue:
        room_id = queue.popleft()
        d = dist[room_id]
        if d >= max_depth:
            continue
        for target in store.list_exits(room_id).values():
            if target not in dist:
                dist[target] = d + 1
                queue.append(target)
    return dist


def build_map_view(
    authority: WorldAuthority,
    *,
    player_character_id: int,
    lod: str = "near",
    presence_by_room: dict[str, list[dict[str, Any]]] | None = None,
    near_radius: int = 2,
) -> dict[str, Any]:
    """Return a fogged, LOD-aware schematic graph for one character.

    Unseen rooms are omitted (fog). Other players appear only on rooms the
    viewer has revealed. Navigation intents are not applied here — map is read-only.
    """
    store = authority.store
    current = store.get_player_room_id(player_character_id)
    seen = _seen_rooms(store, player_character_id)
    positions = _layout_positions(store, current)
    distances = _graph_distance(store, current, max_depth=12) if current else {}
    presence_by_room = presence_by_room or {}
    lod_norm = lod.strip().lower()
    if lod_norm not in {"near", "far", "overview"}:
        lod_norm = "near"

    nodes: list[dict[str, Any]] = []
    for room in store.list_rooms():
        if room.room_id not in seen:
            continue
        dist = distances.get(room.room_id, 99)
        detailed = lod_norm == "near" or dist <= near_radius
        if lod_norm in {"far", "overview"} and dist > near_radius:
            detailed = False
        x, y = positions.get(room.room_id, (0, 0))
        others = [
            {
                "player_character_id": p["player_character_id"],
                "display_name": p["display_name"],
            }
            for p in presence_by_room.get(room.room_id, [])
            if p.get("player_character_id") != player_character_id
        ]
        nodes.append(
            {
                "room_id": room.room_id,
                "name": room.name if detailed else None,
                "x": x,
                "y": y,
                "you_are_here": room.room_id == current,
                "detailed": detailed,
                "others": others,
            }
        )

    edges: list[dict[str, Any]] = []
    for from_id, direction, to_id in store.list_all_exits():
        if from_id not in seen or to_id not in seen:
            continue
        if lod_norm in {"far", "overview"}:
            # Overview keeps edges only when either end is local.
            d_from = distances.get(from_id, 99)
            d_to = distances.get(to_id, 99)
            if d_from > near_radius and d_to > near_radius:
                continue
        edges.append(
            {
                "from": from_id,
                "to": to_id,
                "direction": direction,
            }
        )

    return {
        "lod": lod_norm,
        "current_room_id": current,
        "nodes": nodes,
        "edges": edges,
        "fog": True,
        "note": "Read-only schematic graph; clicks must send move intents to the server.",
    }
