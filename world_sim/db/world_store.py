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
class ItemInstanceRecord:
    id: int
    item_definition_id: str | None
    definition_key: str | None
    location_kind: str
    location_id: str | None
    condition: str | None
    name: str | None = None


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
