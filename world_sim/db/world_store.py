"""World structure, presentation state, and play persistence helpers."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Room:
    room_id: str
    name: str
    lore_key: str


@dataclass(frozen=True)
class ItemDefinition:
    item_id: str
    name: str
    lore_key: str


@dataclass(frozen=True)
class NpcRecord:
    npc_id: str
    name: str
    npc_lore: list[str]
    current_room_id: str | None = None
    condition: str | None = None


@dataclass(frozen=True)
class FrontierStub:
    stub_id: str
    from_room_id: str
    direction: str
    target_room_id: str
    target_name: str
    lore_key: str
    return_direction: str | None = None
    status: str = "pending"


@dataclass(frozen=True)
class ItemInstanceRecord:
    id: int
    item_definition_id: str | None
    definition_key: str | None
    location_kind: str
    location_id: str | None
    condition: str | None
    name: str | None = None


@dataclass(frozen=True)
class MemoryRecord:
    """Bounded runtime memory (Phase 4b1). Not canon lore."""

    id: int
    subject_kind: str
    subject_id: str
    about_kind: str | None
    about_id: str | None
    summary: str
    lore_key: str | None
    created_at: str
    expires_at: str | None


def derive_stable_recap(full_text: str, *, max_len: int = 180) -> str:
    """Derive a stable short recap from full canonical text once."""
    cleaned = " ".join(full_text.split())
    if not cleaned:
        return ""
    match = re.match(r"(.+?[.!?])(\s|$)", cleaned)
    if match:
        sentence = match.group(1).strip()
        if len(sentence) <= max_len:
            return sentence
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


class WorldStore:
    """SQLite-backed rooms, items, presentation, and world clock."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def list_rooms(self) -> list[Room]:
        rows = self._connection.execute(
            "SELECT * FROM rooms ORDER BY room_id"
        ).fetchall()
        return [
            Room(room_id=row["room_id"], name=row["name"], lore_key=row["lore_key"])
            for row in rows
        ]

    def find_rooms_by_lore_key(self, lore_key: str) -> list[Room]:
        rows = self._connection.execute(
            "SELECT * FROM rooms WHERE lore_key = ? ORDER BY room_id",
            (lore_key,),
        ).fetchall()
        return [
            Room(room_id=row["room_id"], name=row["name"], lore_key=row["lore_key"])
            for row in rows
        ]

    def list_item_definitions(self) -> list[ItemDefinition]:
        rows = self._connection.execute(
            "SELECT * FROM item_definitions ORDER BY item_id"
        ).fetchall()
        return [
            ItemDefinition(
                item_id=row["item_id"],
                name=row["name"],
                lore_key=row["lore_key"],
            )
            for row in rows
        ]

    def find_item_definitions_by_lore_key(self, lore_key: str) -> list[ItemDefinition]:
        rows = self._connection.execute(
            "SELECT * FROM item_definitions WHERE lore_key = ? ORDER BY item_id",
            (lore_key,),
        ).fetchall()
        return [
            ItemDefinition(
                item_id=row["item_id"],
                name=row["name"],
                lore_key=row["lore_key"],
            )
            for row in rows
        ]

    def get_meta(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM meta_kv WHERE key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO meta_kv (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def upsert_lore_key_ref(
        self,
        entity_kind: str,
        entity_id: str,
        lore_key: str,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO lore_key_refs (entity_kind, entity_id, lore_key)
                VALUES (?, ?, ?)
                """,
                (entity_kind, entity_id, lore_key),
            )

    def list_lore_keys(self, entity_kind: str, entity_id: str) -> list[str]:
        rows = self._connection.execute(
            """
            SELECT lore_key FROM lore_key_refs
            WHERE entity_kind = ? AND entity_id = ?
            ORDER BY lore_key
            """,
            (entity_kind, entity_id),
        ).fetchall()
        return [str(row["lore_key"]) for row in rows]

    def upsert_room(self, room_id: str, name: str, lore_key: str) -> Room:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO rooms (room_id, name, lore_key)
                VALUES (?, ?, ?)
                ON CONFLICT(room_id) DO UPDATE SET
                    name = excluded.name,
                    lore_key = excluded.lore_key
                """,
                (room_id, name, lore_key),
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO lore_key_refs (entity_kind, entity_id, lore_key)
                VALUES ('room', ?, ?)
                """,
                (room_id, lore_key),
            )
        return Room(room_id=room_id, name=name, lore_key=lore_key)

    def upsert_exit(self, from_room_id: str, direction: str, to_room_id: str) -> None:
        direction_norm = direction.strip().lower()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO room_exits (from_room_id, direction, to_room_id)
                VALUES (?, ?, ?)
                ON CONFLICT(from_room_id, direction) DO UPDATE SET
                    to_room_id = excluded.to_room_id
                """,
                (from_room_id, direction_norm, to_room_id),
            )

    def get_room(self, room_id: str) -> Room | None:
        row = self._connection.execute(
            "SELECT * FROM rooms WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        if row is None:
            return None
        return Room(
            room_id=row["room_id"],
            name=row["name"],
            lore_key=row["lore_key"],
        )

    def list_exits(self, room_id: str) -> dict[str, str]:
        rows = self._connection.execute(
            """
            SELECT direction, to_room_id
            FROM room_exits
            WHERE from_room_id = ?
            ORDER BY direction
            """,
            (room_id,),
        ).fetchall()
        return {str(row["direction"]): str(row["to_room_id"]) for row in rows}

    def list_all_exits(self) -> list[tuple[str, str, str]]:
        """Return all room exits as (from_room_id, direction, to_room_id)."""
        rows = self._connection.execute(
            """
            SELECT from_room_id, direction, to_room_id
            FROM room_exits
            ORDER BY from_room_id, direction
            """
        ).fetchall()
        return [
            (str(row["from_room_id"]), str(row["direction"]), str(row["to_room_id"]))
            for row in rows
        ]

    def list_all_lore_key_refs(self) -> list[tuple[str, str, str]]:
        """Return all lore_key_refs as (entity_kind, entity_id, lore_key)."""
        rows = self._connection.execute(
            """
            SELECT entity_kind, entity_id, lore_key
            FROM lore_key_refs
            ORDER BY entity_kind, entity_id, lore_key
            """
        ).fetchall()
        return [
            (str(row["entity_kind"]), str(row["entity_id"]), str(row["lore_key"]))
            for row in rows
        ]

    def list_all_item_instances(self) -> list[ItemInstanceRecord]:
        rows = self._connection.execute(
            """
            SELECT i.*, d.name AS item_name
            FROM item_instances i
            LEFT JOIN item_definitions d ON d.item_id = i.item_definition_id
            ORDER BY i.id
            """
        ).fetchall()
        return [
            ItemInstanceRecord(
                id=row["id"],
                item_definition_id=row["item_definition_id"],
                definition_key=row["definition_key"],
                location_kind=row["location_kind"],
                location_id=row["location_id"],
                condition=row["condition"],
                name=row["item_name"],
            )
            for row in rows
        ]

    def upsert_item_definition(
        self,
        item_id: str,
        name: str,
        lore_key: str,
    ) -> ItemDefinition:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO item_definitions (item_id, name, lore_key)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    name = excluded.name,
                    lore_key = excluded.lore_key
                """,
                (item_id, name, lore_key),
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO lore_key_refs (entity_kind, entity_id, lore_key)
                VALUES ('item_definition', ?, ?)
                """,
                (item_id, lore_key),
            )
        return ItemDefinition(item_id=item_id, name=name, lore_key=lore_key)

    def get_item_definition(self, item_id: str) -> ItemDefinition | None:
        row = self._connection.execute(
            "SELECT * FROM item_definitions WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return ItemDefinition(
            item_id=row["item_id"],
            name=row["name"],
            lore_key=row["lore_key"],
        )

    def create_item_instance(
        self,
        *,
        item_definition_id: str,
        location_kind: str,
        location_id: str | None,
        condition: str | None = None,
    ) -> ItemInstanceRecord:
        definition = self.get_item_definition(item_definition_id)
        if definition is None:
            raise ValueError(f"Unknown item definition: {item_definition_id}")
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO item_instances (
                    item_definition_id, definition_key, location_kind, location_id, condition
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    item_definition_id,
                    definition.lore_key,
                    location_kind,
                    location_id,
                    condition,
                ),
            )
            item_id = int(cursor.lastrowid)
        record = self.get_item_instance(item_id)
        if record is None:
            raise RuntimeError("Failed to load item instance.")
        return record

    def get_item_instance(self, item_instance_id: int) -> ItemInstanceRecord | None:
        row = self._connection.execute(
            """
            SELECT i.*, d.name AS item_name
            FROM item_instances i
            LEFT JOIN item_definitions d ON d.item_id = i.item_definition_id
            WHERE i.id = ?
            """,
            (item_instance_id,),
        ).fetchone()
        if row is None:
            return None
        return ItemInstanceRecord(
            id=row["id"],
            item_definition_id=row["item_definition_id"],
            definition_key=row["definition_key"],
            location_kind=row["location_kind"],
            location_id=row["location_id"],
            condition=row["condition"],
            name=row["item_name"],
        )

    def list_items_in_room(self, room_id: str) -> list[ItemInstanceRecord]:
        rows = self._connection.execute(
            """
            SELECT i.*, d.name AS item_name
            FROM item_instances i
            LEFT JOIN item_definitions d ON d.item_id = i.item_definition_id
            WHERE i.location_kind = 'room' AND i.location_id = ?
            ORDER BY i.id
            """,
            (room_id,),
        ).fetchall()
        return [
            ItemInstanceRecord(
                id=row["id"],
                item_definition_id=row["item_definition_id"],
                definition_key=row["definition_key"],
                location_kind=row["location_kind"],
                location_id=row["location_id"],
                condition=row["condition"],
                name=row["item_name"],
            )
            for row in rows
        ]

    def list_player_items(self, player_character_id: int) -> list[ItemInstanceRecord]:
        rows = self._connection.execute(
            """
            SELECT i.*, d.name AS item_name
            FROM player_inventory inv
            JOIN item_instances i ON i.id = inv.item_instance_id
            LEFT JOIN item_definitions d ON d.item_id = i.item_definition_id
            WHERE inv.player_character_id = ?
            ORDER BY i.id
            """,
            (player_character_id,),
        ).fetchall()
        return [
            ItemInstanceRecord(
                id=row["id"],
                item_definition_id=row["item_definition_id"],
                definition_key=row["definition_key"],
                location_kind=row["location_kind"],
                location_id=row["location_id"],
                condition=row["condition"],
                name=row["item_name"],
            )
            for row in rows
        ]

    def get_player_room_id(self, player_character_id: int) -> str | None:
        row = self._connection.execute(
            "SELECT current_room_id FROM player_characters WHERE id = ?",
            (player_character_id,),
        ).fetchone()
        if row is None or row["current_room_id"] is None:
            return None
        return str(row["current_room_id"])

    def set_player_room(self, player_character_id: int, room_id: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE player_characters
                SET current_room_id = ?
                WHERE id = ?
                """,
                (room_id, player_character_id),
            )

    def move_player(self, player_character_id: int, direction: str) -> Room:
        direction_norm = direction.strip().lower()
        current = self.get_player_room_id(player_character_id)
        if current is None:
            raise ValueError("Player has no current room.")
        exits = self.list_exits(current)
        target = exits.get(direction_norm)
        if target is None:
            raise ValueError(f"No exit '{direction_norm}' from this room.")
        self.set_player_room(player_character_id, target)
        room = self.get_room(target)
        if room is None:
            raise ValueError(f"Missing room record for {target}.")
        return room

    def take_item_from_room(
        self,
        player_character_id: int,
        item_instance_id: int,
    ) -> ItemInstanceRecord:
        room_id = self.get_player_room_id(player_character_id)
        if room_id is None:
            raise ValueError("Player has no current room.")
        item = self.get_item_instance(item_instance_id)
        if item is None:
            raise ValueError("That item is not here.")
        if item.location_kind != "room" or item.location_id != room_id:
            raise ValueError("That item is not in this room.")
        with self._connection:
            self._connection.execute(
                """
                UPDATE item_instances
                SET location_kind = 'player_character', location_id = ?
                WHERE id = ?
                """,
                (str(player_character_id), item_instance_id),
            )
            self._connection.execute(
                """
                INSERT OR REPLACE INTO player_inventory (
                    player_character_id, item_instance_id
                )
                VALUES (?, ?)
                """,
                (player_character_id, item_instance_id),
            )
        updated = self.get_item_instance(item_instance_id)
        if updated is None:
            raise RuntimeError("Failed to reload item after take.")
        return updated

    def find_room_item_by_name(
        self,
        room_id: str,
        name_query: str,
    ) -> ItemInstanceRecord | None:
        query = name_query.strip().lower()
        for item in self.list_items_in_room(room_id):
            if item.name and query in item.name.lower():
                return item
        return None

    def find_visible_item_by_name(
        self,
        player_character_id: int,
        name_query: str,
    ) -> ItemInstanceRecord | None:
        query = name_query.strip().lower()
        room_id = self.get_player_room_id(player_character_id)
        candidates = list(self.list_player_items(player_character_id))
        if room_id is not None:
            candidates.extend(self.list_items_in_room(room_id))
        for item in candidates:
            if item.name and query in item.name.lower():
                return item
        return None

    def get_minutes_elapsed(self) -> int:
        row = self._connection.execute(
            "SELECT minutes_elapsed FROM world_clock WHERE id = 1"
        ).fetchone()
        return int(row["minutes_elapsed"]) if row else 0

    def advance_time(self, minutes: int) -> int:
        if minutes < 0:
            raise ValueError("minutes must be non-negative")
        with self._connection:
            self._connection.execute(
                """
                UPDATE world_clock
                SET minutes_elapsed = minutes_elapsed + ?
                WHERE id = 1
                """,
                (minutes,),
            )
        return self.get_minutes_elapsed()

    def get_room_presentation(
        self,
        player_character_id: int,
        room_id: str,
    ) -> tuple[bool, str | None]:
        row = self._connection.execute(
            """
            SELECT full_description_seen, stable_recap
            FROM room_presentation_state
            WHERE player_character_id = ? AND room_id = ?
            """,
            (player_character_id, room_id),
        ).fetchone()
        if row is None:
            return False, None
        return bool(row["full_description_seen"]), row["stable_recap"]

    def mark_room_full_description_seen(
        self,
        player_character_id: int,
        room_id: str,
        stable_recap: str,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO room_presentation_state (
                    player_character_id, room_id, full_description_seen, stable_recap
                )
                VALUES (?, ?, 1, ?)
                ON CONFLICT(player_character_id, room_id) DO UPDATE SET
                    full_description_seen = 1,
                    stable_recap = COALESCE(
                        room_presentation_state.stable_recap,
                        excluded.stable_recap
                    )
                """,
                (player_character_id, room_id, stable_recap),
            )

    def invalidate_room_presentation(self, room_id: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE room_presentation_state
                SET full_description_seen = 0, stable_recap = NULL
                WHERE room_id = ?
                """,
                (room_id,),
            )

    def get_item_presentation(
        self,
        player_character_id: int,
        item_instance_id: int,
    ) -> tuple[bool, str | None]:
        row = self._connection.execute(
            """
            SELECT full_description_seen, stable_recap
            FROM item_presentation_state
            WHERE player_character_id = ? AND item_instance_id = ?
            """,
            (player_character_id, item_instance_id),
        ).fetchone()
        if row is None:
            return False, None
        return bool(row["full_description_seen"]), row["stable_recap"]

    def mark_item_full_description_seen(
        self,
        player_character_id: int,
        item_instance_id: int,
        stable_recap: str,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO item_presentation_state (
                    player_character_id, item_instance_id,
                    full_description_seen, stable_recap
                )
                VALUES (?, ?, 1, ?)
                ON CONFLICT(player_character_id, item_instance_id) DO UPDATE SET
                    full_description_seen = 1,
                    stable_recap = COALESCE(
                        item_presentation_state.stable_recap,
                        excluded.stable_recap
                    )
                """,
                (player_character_id, item_instance_id, stable_recap),
            )

    def invalidate_item_presentation_for_definition(self, item_definition_id: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE item_presentation_state
                SET full_description_seen = 0, stable_recap = NULL
                WHERE item_instance_id IN (
                    SELECT id FROM item_instances
                    WHERE item_definition_id = ?
                )
                """,
                (item_definition_id,),
            )

    def upsert_npc(
        self,
        npc_id: str,
        name: str,
        *,
        npc_lore: list[str],
        current_room_id: str | None = None,
        condition: str | None = None,
    ) -> NpcRecord:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO npcs (npc_id, name, current_room_id, condition)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(npc_id) DO UPDATE SET
                    name = excluded.name,
                    current_room_id = excluded.current_room_id,
                    condition = excluded.condition
                """,
                (npc_id, name, current_room_id, condition),
            )
            self._connection.execute(
                "DELETE FROM npc_lore_keys WHERE npc_id = ?",
                (npc_id,),
            )
            for index, lore_key in enumerate(npc_lore):
                self._connection.execute(
                    """
                    INSERT INTO npc_lore_keys (npc_id, lore_key, sort_order)
                    VALUES (?, ?, ?)
                    """,
                    (npc_id, lore_key, index),
                )
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO lore_key_refs (entity_kind, entity_id, lore_key)
                    VALUES ('npc', ?, ?)
                    """,
                    (npc_id, lore_key),
                )
        record = self.get_npc(npc_id)
        if record is None:
            raise RuntimeError(f"Failed to load NPC '{npc_id}'.")
        return record

    def get_npc(self, npc_id: str) -> NpcRecord | None:
        row = self._connection.execute(
            "SELECT * FROM npcs WHERE npc_id = ?",
            (npc_id,),
        ).fetchone()
        if row is None:
            return None
        lore_rows = self._connection.execute(
            """
            SELECT lore_key FROM npc_lore_keys
            WHERE npc_id = ?
            ORDER BY sort_order ASC, lore_key ASC
            """,
            (npc_id,),
        ).fetchall()
        return NpcRecord(
            npc_id=row["npc_id"],
            name=row["name"],
            npc_lore=[str(item["lore_key"]) for item in lore_rows],
            current_room_id=row["current_room_id"],
            condition=row["condition"],
        )

    def list_npcs(self) -> list[NpcRecord]:
        rows = self._connection.execute(
            "SELECT npc_id FROM npcs ORDER BY npc_id"
        ).fetchall()
        npcs: list[NpcRecord] = []
        for row in rows:
            npc = self.get_npc(str(row["npc_id"]))
            if npc is not None:
                npcs.append(npc)
        return npcs

    def list_npcs_in_room(self, room_id: str) -> list[NpcRecord]:
        rows = self._connection.execute(
            """
            SELECT npc_id FROM npcs
            WHERE current_room_id = ?
            ORDER BY npc_id
            """,
            (room_id,),
        ).fetchall()
        npcs: list[NpcRecord] = []
        for row in rows:
            npc = self.get_npc(str(row["npc_id"]))
            if npc is not None:
                npcs.append(npc)
        return npcs

    def find_npc_by_name(self, name_query: str) -> NpcRecord | None:
        query = name_query.strip().lower()
        for npc in self.list_npcs():
            if query in npc.name.lower() or query == npc.npc_id.lower():
                return npc
        return None

    def set_npc_room(self, npc_id: str, room_id: str | None) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE npcs SET current_room_id = ? WHERE npc_id = ?",
                (room_id, npc_id),
            )

    def set_npc_condition(self, npc_id: str, condition: str | None) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE npcs SET condition = ? WHERE npc_id = ?",
                (condition, npc_id),
            )

    def get_npc_presentation(
        self,
        player_character_id: int,
        npc_id: str,
    ) -> tuple[bool, str | None]:
        row = self._connection.execute(
            """
            SELECT full_description_seen, stable_recap
            FROM npc_presentation_state
            WHERE player_character_id = ? AND npc_id = ?
            """,
            (player_character_id, npc_id),
        ).fetchone()
        if row is None:
            return False, None
        return bool(row["full_description_seen"]), row["stable_recap"]

    def mark_npc_full_description_seen(
        self,
        player_character_id: int,
        npc_id: str,
        stable_recap: str,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO npc_presentation_state (
                    player_character_id, npc_id,
                    full_description_seen, stable_recap
                )
                VALUES (?, ?, 1, ?)
                ON CONFLICT(player_character_id, npc_id) DO UPDATE SET
                    full_description_seen = 1,
                    stable_recap = COALESCE(
                        npc_presentation_state.stable_recap,
                        excluded.stable_recap
                    )
                """,
                (player_character_id, npc_id, stable_recap),
            )

    def invalidate_npc_presentation(self, npc_id: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE npc_presentation_state
                SET full_description_seen = 0, stable_recap = NULL
                WHERE npc_id = ?
                """,
                (npc_id,),
            )

    def upsert_frontier_stub(
        self,
        *,
        stub_id: str,
        from_room_id: str,
        direction: str,
        target_room_id: str,
        target_name: str,
        lore_key: str,
        return_direction: str | None = None,
    ) -> FrontierStub:
        direction_norm = direction.strip().lower()
        return_norm = (
            return_direction.strip().lower() if return_direction else None
        )
        if self.get_room(from_room_id) is None:
            raise ValueError(f"Unknown from_room_id '{from_room_id}'.")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO frontier_stubs (
                    stub_id, from_room_id, direction, target_room_id,
                    target_name, lore_key, return_direction, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(stub_id) DO UPDATE SET
                    from_room_id = excluded.from_room_id,
                    direction = excluded.direction,
                    target_room_id = excluded.target_room_id,
                    target_name = excluded.target_name,
                    lore_key = excluded.lore_key,
                    return_direction = excluded.return_direction,
                    status = 'pending',
                    realized_at = NULL
                """,
                (
                    stub_id,
                    from_room_id,
                    direction_norm,
                    target_room_id,
                    target_name,
                    lore_key,
                    return_norm,
                ),
            )
        stub = self.get_frontier_stub(stub_id)
        if stub is None:
            raise RuntimeError("Failed to load frontier stub.")
        return stub

    def get_frontier_stub(self, stub_id: str) -> FrontierStub | None:
        row = self._connection.execute(
            "SELECT * FROM frontier_stubs WHERE stub_id = ?",
            (stub_id,),
        ).fetchone()
        return self._stub_from_row(row) if row else None

    def get_pending_stub(
        self,
        from_room_id: str,
        direction: str,
    ) -> FrontierStub | None:
        direction_norm = direction.strip().lower()
        row = self._connection.execute(
            """
            SELECT * FROM frontier_stubs
            WHERE from_room_id = ? AND direction = ? AND status = 'pending'
            """,
            (from_room_id, direction_norm),
        ).fetchone()
        return self._stub_from_row(row) if row else None

    def list_frontier_stubs(self, *, status: str | None = None) -> list[FrontierStub]:
        if status is None:
            rows = self._connection.execute(
                "SELECT * FROM frontier_stubs ORDER BY from_room_id, direction"
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM frontier_stubs
                WHERE status = ?
                ORDER BY from_room_id, direction
                """,
                (status,),
            ).fetchall()
        return [self._stub_from_row(row) for row in rows]

    def list_pending_stub_directions(self, from_room_id: str) -> dict[str, str]:
        """Return direction -> target_room_id for pending stubs from a room."""
        rows = self._connection.execute(
            """
            SELECT direction, target_room_id FROM frontier_stubs
            WHERE from_room_id = ? AND status = 'pending'
            ORDER BY direction
            """,
            (from_room_id,),
        ).fetchall()
        return {
            str(row["direction"]): str(row["target_room_id"]) for row in rows
        }

    def mark_stub_realized(self, stub_id: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE frontier_stubs
                SET status = 'realized',
                    realized_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE stub_id = ?
                """,
                (stub_id,),
            )

    def append_runtime_event(self, event_type: str, payload: dict) -> int:
        import json

        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO runtime_events (event_type, payload_json)
                VALUES (?, ?)
                """,
                (event_type, json.dumps(payload, sort_keys=True)),
            )
            return int(cursor.lastrowid)

    def list_runtime_events(
        self,
        *,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[tuple[int, str, str, str]]:
        if event_type:
            rows = self._connection.execute(
                """
                SELECT id, event_type, payload_json, created_at
                FROM runtime_events
                WHERE event_type = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (event_type, limit),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, event_type, payload_json, created_at
                FROM runtime_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            (
                int(row["id"]),
                str(row["event_type"]),
                str(row["payload_json"]),
                str(row["created_at"]),
            )
            for row in rows
        ]

    # --- Bounded memory (Phase 4b1; runtime state, not canon) ---

    def purge_expired_memories(self) -> int:
        with self._connection:
            cursor = self._connection.execute(
                """
                DELETE FROM bounded_memories
                WHERE expires_at IS NOT NULL
                  AND expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """
            )
            return int(cursor.rowcount)

    def get_memory(self, memory_id: int) -> MemoryRecord | None:
        self.purge_expired_memories()
        row = self._connection.execute(
            "SELECT * FROM bounded_memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return self._memory_from_row(row)

    def insert_memory(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        summary: str,
        about_kind: str | None = None,
        about_id: str | None = None,
        lore_key: str | None = None,
        expires_at: str | None = None,
    ) -> MemoryRecord:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO bounded_memories (
                    subject_kind, subject_id, about_kind, about_id,
                    summary, lore_key, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subject_kind,
                    subject_id,
                    about_kind,
                    about_id,
                    summary,
                    lore_key,
                    expires_at,
                ),
            )
            memory_id = int(cursor.lastrowid)
        record = self.get_memory(memory_id)
        assert record is not None
        return record

    def delete_memory(self, memory_id: int) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM bounded_memories WHERE id = ?",
                (memory_id,),
            )
            return cursor.rowcount > 0

    def count_memories_for_subject(self, subject_kind: str, subject_id: str) -> int:
        self.purge_expired_memories()
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS n FROM bounded_memories
            WHERE subject_kind = ? AND subject_id = ?
            """,
            (subject_kind, subject_id),
        ).fetchone()
        return int(row["n"]) if row else 0

    def trim_memories_for_subject(
        self,
        subject_kind: str,
        subject_id: str,
        *,
        keep: int,
    ) -> int:
        """Delete oldest memories beyond ``keep``. Returns rows deleted."""
        if keep < 0:
            raise ValueError("keep must be >= 0")
        self.purge_expired_memories()
        rows = self._connection.execute(
            """
            SELECT id FROM bounded_memories
            WHERE subject_kind = ? AND subject_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (subject_kind, subject_id),
        ).fetchall()
        excess = len(rows) - keep
        if excess <= 0:
            return 0
        to_delete = [int(row["id"]) for row in rows[:excess]]
        with self._connection:
            self._connection.executemany(
                "DELETE FROM bounded_memories WHERE id = ?",
                [(memory_id,) for memory_id in to_delete],
            )
        return excess

    def list_memories_for_subject(
        self,
        subject_kind: str,
        subject_id: str,
        *,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        self.purge_expired_memories()
        rows = self._connection.execute(
            """
            SELECT * FROM bounded_memories
            WHERE subject_kind = ? AND subject_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (subject_kind, subject_id, limit),
        ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def list_npc_memories_about_player(
        self,
        npc_id: str,
        player_character_id: int,
        *,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """NPC-subject memories tagged about a specific player character."""
        self.purge_expired_memories()
        rows = self._connection.execute(
            """
            SELECT * FROM bounded_memories
            WHERE subject_kind = 'npc'
              AND subject_id = ?
              AND about_kind = 'player_character'
              AND about_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (npc_id, str(player_character_id), limit),
        ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    @staticmethod
    def _memory_from_row(row: object) -> MemoryRecord:
        return MemoryRecord(
            id=int(row["id"]),  # type: ignore[index]
            subject_kind=str(row["subject_kind"]),  # type: ignore[index]
            subject_id=str(row["subject_id"]),  # type: ignore[index]
            about_kind=row["about_kind"],  # type: ignore[index]
            about_id=row["about_id"],  # type: ignore[index]
            summary=str(row["summary"]),  # type: ignore[index]
            lore_key=row["lore_key"],  # type: ignore[index]
            created_at=str(row["created_at"]),  # type: ignore[index]
            expires_at=row["expires_at"],  # type: ignore[index]
        )

    @staticmethod
    def _stub_from_row(row: object) -> FrontierStub:
        return FrontierStub(
            stub_id=str(row["stub_id"]),  # type: ignore[index]
            from_room_id=str(row["from_room_id"]),  # type: ignore[index]
            direction=str(row["direction"]),  # type: ignore[index]
            target_room_id=str(row["target_room_id"]),  # type: ignore[index]
            target_name=str(row["target_name"]),  # type: ignore[index]
            lore_key=str(row["lore_key"]),  # type: ignore[index]
            return_direction=row["return_direction"],  # type: ignore[index]
            status=str(row["status"]),  # type: ignore[index]
        )
