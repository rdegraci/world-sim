"""User, player character, session, and inventory persistence helpers."""

from __future__ import annotations

import sqlite3

from world_sim.models import (
    ItemInstance,
    PlayerCharacter,
    SessionRecord,
    TranscriptEntry,
    User,
)


class AuthStoreError(Exception):
    """Raised for identity or session persistence failures."""


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
    )


def _player_from_row(row: sqlite3.Row) -> PlayerCharacter:
    return PlayerCharacter(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        created_at=row["created_at"],
    )


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        user_id=row["user_id"],
        player_character_id=row["player_character_id"],
        status=row["status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
    )


def _transcript_from_row(row: sqlite3.Row) -> TranscriptEntry:
    return TranscriptEntry(
        id=row["id"],
        session_id=row["session_id"],
        sequence_no=row["sequence_no"],
        speaker=row["speaker"],
        content=row["content"],
        created_at=row["created_at"],
    )


def _item_from_row(row: sqlite3.Row) -> ItemInstance:
    return ItemInstance(
        id=row["id"],
        definition_key=row["definition_key"],
        location_kind=row["location_kind"],
        location_id=row["location_id"],
        condition=row["condition"],
        created_at=row["created_at"],
    )


class UserStore:
    """SQLite-backed identity, session, and inventory operations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def get_user_by_username(self, username: str) -> User | None:
        row = self._connection.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        return _user_from_row(row) if row else None

    def create_player_user(self, username: str, password_hash: str) -> User:
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT INTO users (username, role, password_hash)
                    VALUES (?, 'player', ?)
                    """,
                    (username, password_hash),
                )
                user_id = int(cursor.lastrowid)
                self._connection.execute(
                    """
                    INSERT INTO player_characters (user_id, name)
                    VALUES (?, ?)
                    """,
                    (user_id, username),
                )
        except sqlite3.IntegrityError as exc:
            raise AuthStoreError(
                f"Username '{username}' is already taken or violates one-user-one-player rules."
            ) from exc
        user = self.get_user_by_username(username)
        if user is None:
            raise AuthStoreError("Failed to load newly created user.")
        return user

    def ensure_admin_user(self, username: str = "admin") -> User:
        existing = self.get_user_by_username(username)
        if existing is not None:
            if existing.role != "admin":
                raise AuthStoreError(
                    f"Username '{username}' exists but is not an admin account."
                )
            player = self.get_player_character_for_user(existing.id)
            if player is None:
                with self._connection:
                    self._connection.execute(
                        """
                        INSERT INTO player_characters (user_id, name)
                        VALUES (?, ?)
                        """,
                        (existing.id, username),
                    )
            return existing

        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT INTO users (username, role, password_hash)
                    VALUES (?, 'admin', NULL)
                    """,
                    (username,),
                )
                user_id = int(cursor.lastrowid)
                self._connection.execute(
                    """
                    INSERT INTO player_characters (user_id, name)
                    VALUES (?, ?)
                    """,
                    (user_id, username),
                )
        except sqlite3.IntegrityError as exc:
            raise AuthStoreError(
                f"Could not create admin user '{username}'."
            ) from exc

        user = self.get_user_by_username(username)
        if user is None:
            raise AuthStoreError("Failed to load newly created admin user.")
        return user

    def get_player_character_for_user(self, user_id: int) -> PlayerCharacter | None:
        row = self._connection.execute(
            "SELECT * FROM player_characters WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return _player_from_row(row) if row else None

    def require_player_character_for_user(self, user_id: int) -> PlayerCharacter:
        player = self.get_player_character_for_user(user_id)
        if player is None:
            raise AuthStoreError(
                f"User id {user_id} has no player_character (MVP requires exactly one)."
            )
        return player

    def create_session(self, user_id: int, player_character_id: int) -> SessionRecord:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO sessions (user_id, player_character_id, status)
                VALUES (?, ?, 'active')
                """,
                (user_id, player_character_id),
            )
            session_id = int(cursor.lastrowid)
        row = self._connection.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise AuthStoreError("Failed to load newly created session.")
        return _session_from_row(row)

    def end_session(self, session_id: int) -> SessionRecord:
        with self._connection:
            self._connection.execute(
                """
                UPDATE sessions
                SET status = 'ended',
                    ended_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (session_id,),
            )
        row = self._connection.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise AuthStoreError(f"Session {session_id} not found.")
        return _session_from_row(row)

    def append_transcript(
        self,
        session_id: int,
        speaker: str,
        content: str,
    ) -> TranscriptEntry:
        with self._connection:
            current = self._connection.execute(
                """
                SELECT COALESCE(MAX(sequence_no), 0) AS max_seq
                FROM transcripts
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            next_seq = int(current["max_seq"]) + 1 if current else 1
            cursor = self._connection.execute(
                """
                INSERT INTO transcripts (session_id, sequence_no, speaker, content)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, next_seq, speaker, content),
            )
            entry_id = int(cursor.lastrowid)
        row = self._connection.execute(
            "SELECT * FROM transcripts WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise AuthStoreError("Failed to load newly created transcript entry.")
        return _transcript_from_row(row)

    def list_transcripts(self, session_id: int) -> list[TranscriptEntry]:
        rows = self._connection.execute(
            """
            SELECT * FROM transcripts
            WHERE session_id = ?
            ORDER BY sequence_no ASC
            """,
            (session_id,),
        ).fetchall()
        return [_transcript_from_row(row) for row in rows]

    def create_item_instance(
        self,
        *,
        definition_key: str | None = None,
        location_kind: str = "unplaced",
        location_id: str | None = None,
        condition: str | None = None,
    ) -> ItemInstance:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO item_instances (
                    definition_key, location_kind, location_id, condition
                )
                VALUES (?, ?, ?, ?)
                """,
                (definition_key, location_kind, location_id, condition),
            )
            item_id = int(cursor.lastrowid)
        row = self._connection.execute(
            "SELECT * FROM item_instances WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise AuthStoreError("Failed to load newly created item instance.")
        return _item_from_row(row)

    def add_item_to_player_inventory(
        self,
        player_character_id: int,
        item_instance_id: int,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE item_instances
                SET location_kind = 'player_character',
                    location_id = ?
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

    def list_player_inventory(self, player_character_id: int) -> list[ItemInstance]:
        rows = self._connection.execute(
            """
            SELECT i.*
            FROM player_inventory inv
            JOIN item_instances i ON i.id = inv.item_instance_id
            WHERE inv.player_character_id = ?
            ORDER BY i.id ASC
            """,
            (player_character_id,),
        ).fetchall()
        return [_item_from_row(row) for row in rows]
