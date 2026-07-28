"""Domain models for identity and session runtime records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str
    password_hash: str | None
    created_at: str


@dataclass(frozen=True)
class PlayerCharacter:
    id: int
    user_id: int
    name: str
    created_at: str


@dataclass(frozen=True)
class SessionRecord:
    id: int
    user_id: int
    player_character_id: int
    status: str
    started_at: str
    ended_at: str | None


@dataclass(frozen=True)
class TranscriptEntry:
    id: int
    session_id: int
    sequence_no: int
    speaker: str
    content: str
    created_at: str


@dataclass(frozen=True)
class ItemInstance:
    id: int
    definition_key: str | None
    location_kind: str
    location_id: str | None
    condition: str | None
    created_at: str


@dataclass(frozen=True)
class AuthContext:
    """Authenticated runtime identity for the local session loop."""

    user: User
    player_character: PlayerCharacter
    session: SessionRecord

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"
