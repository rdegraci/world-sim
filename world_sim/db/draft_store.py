"""Pending lore draft persistence for review-before-save flows."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class LoreDraft:
    id: int
    collection_name: str
    proposed_key: str
    prompt: str | None
    draft_text: str
    status: str
    created_by_user_id: int | None
    created_at: str
    reviewed_at: str | None


def _draft_from_row(row: sqlite3.Row) -> LoreDraft:
    return LoreDraft(
        id=row["id"],
        collection_name=row["collection_name"],
        proposed_key=row["proposed_key"],
        prompt=row["prompt"],
        draft_text=row["draft_text"],
        status=row["status"],
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
    )


class DraftStore:
    """SQLite-backed reviewable lore drafts."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create_draft(
        self,
        *,
        collection_name: str,
        proposed_key: str,
        draft_text: str,
        prompt: str | None,
        created_by_user_id: int | None,
    ) -> LoreDraft:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO lore_drafts (
                    collection_name, proposed_key, prompt, draft_text,
                    status, created_by_user_id
                )
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (
                    collection_name,
                    proposed_key,
                    prompt,
                    draft_text,
                    created_by_user_id,
                ),
            )
            draft_id = int(cursor.lastrowid)
        draft = self.get_draft(draft_id)
        if draft is None:
            raise RuntimeError("Failed to load newly created draft.")
        return draft

    def get_draft(self, draft_id: int) -> LoreDraft | None:
        row = self._connection.execute(
            "SELECT * FROM lore_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        return _draft_from_row(row) if row else None

    def list_drafts(self, *, status: str | None = "pending") -> list[LoreDraft]:
        if status is None:
            rows = self._connection.execute(
                "SELECT * FROM lore_drafts ORDER BY id DESC"
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM lore_drafts
                WHERE status = ?
                ORDER BY id DESC
                """,
                (status,),
            ).fetchall()
        return [_draft_from_row(row) for row in rows]

    def set_status(self, draft_id: int, status: str) -> LoreDraft:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"Invalid draft status: {status}")
        with self._connection:
            self._connection.execute(
                """
                UPDATE lore_drafts
                SET status = ?,
                    reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (status, draft_id),
            )
        draft = self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"Draft {draft_id} not found.")
        return draft
