"""SQLite schema initialization and connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role TEXT NOT NULL CHECK (role IN ('player', 'admin')),
    password_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (role = 'admin' AND password_hash IS NULL)
        OR (role = 'player' AND password_hash IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS player_characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    current_room_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lore_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS room_exits (
    from_room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    direction TEXT NOT NULL,
    to_room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    PRIMARY KEY (from_room_id, direction)
);

CREATE TABLE IF NOT EXISTS item_definitions (
    item_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lore_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_definition_id TEXT REFERENCES item_definitions(item_id),
    definition_key TEXT,
    location_kind TEXT NOT NULL CHECK (
        location_kind IN ('room', 'player_character', 'npc', 'unplaced')
    ),
    location_id TEXT,
    condition TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS player_inventory (
    player_character_id INTEGER NOT NULL
        REFERENCES player_characters(id) ON DELETE CASCADE,
    item_instance_id INTEGER NOT NULL UNIQUE
        REFERENCES item_instances(id) ON DELETE CASCADE,
    PRIMARY KEY (player_character_id, item_instance_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    player_character_id INTEGER NOT NULL
        REFERENCES player_characters(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('active', 'ended')),
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    speaker TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (session_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS world_clock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    minutes_elapsed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS room_presentation_state (
    player_character_id INTEGER NOT NULL
        REFERENCES player_characters(id) ON DELETE CASCADE,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    full_description_seen INTEGER NOT NULL DEFAULT 0,
    stable_recap TEXT,
    PRIMARY KEY (player_character_id, room_id)
);

CREATE TABLE IF NOT EXISTS item_presentation_state (
    player_character_id INTEGER NOT NULL
        REFERENCES player_characters(id) ON DELETE CASCADE,
    item_instance_id INTEGER NOT NULL
        REFERENCES item_instances(id) ON DELETE CASCADE,
    full_description_seen INTEGER NOT NULL DEFAULT 0,
    stable_recap TEXT,
    PRIMARY KEY (player_character_id, item_instance_id)
);

CREATE TABLE IF NOT EXISTS lore_key_refs (
    entity_kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    lore_key TEXT NOT NULL,
    PRIMARY KEY (entity_kind, entity_id, lore_key)
);

CREATE TABLE IF NOT EXISTS meta_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    ddl_type: str,
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    names = {row[1] for row in rows}
    if column not in names:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


class SqliteManager:
    """Owns the SQLite connection used for MVP structured runtime state."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._connection: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._connection = connection
        return self._connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self.connect()

    def initialize_schema(self) -> None:
        connection = self.connect()
        connection.executescript(SCHEMA_SQL)
        _ensure_column(connection, "player_characters", "current_room_id", "TEXT")
        _ensure_column(connection, "item_instances", "item_definition_id", "TEXT")
        connection.execute(
            """
            INSERT OR IGNORE INTO world_clock (id, minutes_elapsed)
            VALUES (1, 0)
            """
        )
        connection.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> SqliteManager:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
