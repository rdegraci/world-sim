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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS item_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
"""


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
