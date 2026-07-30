"""In-process runtime event bus with durable SQLite persistence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from world_sim.authority.events import RuntimeEvent
from world_sim.db.world_store import WorldStore

EventHandler = Callable[[RuntimeEvent], None]


class RuntimeEventBus:
    """Persist scene-public events and notify local subscribers.

    CLI may ignore fan-out; Phase 3b WebSockets will subscribe here (or to an
    equivalent API) without changing mutation sites.
    """

    def __init__(self, store: WorldStore) -> None:
        self._store = store
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._subscribers = [h for h in self._subscribers if h is not handler]

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        room_ids: tuple[str, ...] = (),
    ) -> RuntimeEvent:
        event_id = self._store.append_runtime_event(event_type, payload)
        event = RuntimeEvent(
            id=event_id,
            event_type=event_type,
            payload=dict(payload),
            room_ids=room_ids,
        )
        for handler in list(self._subscribers):
            handler(event)
        return event

    def list_events(
        self,
        *,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[RuntimeEvent]:
        rows = self._store.list_runtime_events(event_type=event_type, limit=limit)
        events: list[RuntimeEvent] = []
        for event_id, etype, payload_json, created_at in rows:
            import json

            payload = json.loads(payload_json)
            room_ids = tuple(payload.get("room_ids") or ())
            if not room_ids:
                # Infer from common payload keys for older / simple rows.
                inferred: list[str] = []
                for key in ("room_id", "from_room_id", "to_room_id"):
                    value = payload.get(key)
                    if isinstance(value, str) and value not in inferred:
                        inferred.append(value)
                room_ids = tuple(inferred)
            events.append(
                RuntimeEvent(
                    id=event_id,
                    event_type=etype,
                    payload=payload,
                    created_at=created_at,
                    room_ids=room_ids,
                )
            )
        return events
