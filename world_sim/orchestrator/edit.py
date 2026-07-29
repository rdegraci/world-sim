"""Admin-only constrained edit_mode for canonical lore operations."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from world_sim.db.draft_store import DraftStore
from world_sim.db.world_store import WorldStore
from world_sim.llm.base import ChatMessage, LLMAdapter
from world_sim.lore.chroma_manager import (
    COLLECTION_ITEM,
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)
from world_sim.models import AuthContext
from world_sim.orchestrator.prompts import compose_edit_system_prompt
from world_sim.utils.logger import get_logger

EDIT_HELP = """\
edit_mode commands (admin only):
  help
  mode play                 Leave edit_mode and return to play_mode

  list_system_lore [search=...]
  view_system_lore <key>
  add_system_lore <key> | <text...>
  create_system_lore <prompt...>
  list_drafts
  view_draft <id>
  approve_draft <id>
  reject_draft <id>

  list_room_lore [search=...]
  view_room_lore <key>
  add_room_lore <room_id> | <text...>

  list_item_lore [search=...]
  view_item_lore <key>
  add_item_lore <item_id> | <text...>

Notes:
  - create_system_lore stores a pending draft only.
  - approve_draft is required before generated lore becomes canonical.
  - Canon edits invalidate affected room/item presentation state.
"""


@dataclass(frozen=True)
class EditResult:
    message: str
    ok: bool = True


class EditAccessError(Exception):
    """Raised when a non-admin attempts edit_mode operations."""


class EditOrchestrator:
    """Narrow admin canon operations with review-before-save for generated lore."""

    def __init__(
        self,
        *,
        world: WorldStore,
        lore: ChromaManager,
        drafts: DraftStore,
        llm: LLMAdapter,
        auth: AuthContext,
    ) -> None:
        self.world = world
        self.lore = lore
        self.drafts = drafts
        self.llm = llm
        self.auth = auth
        self.system_prompt = compose_edit_system_prompt()
        self._logger = get_logger("edit")

    def assert_admin(self) -> None:
        if not self.auth.is_admin:
            raise EditAccessError(
                "edit_mode is admin-only. Non-admin users cannot access canon operations."
            )

    def handle(self, line: str) -> EditResult:
        self.assert_admin()
        raw = line.strip()
        if not raw:
            return EditResult(ok=False, message="Empty edit command.")

        lowered = raw.lower()
        if lowered in {"help", "edit help", "?"}:
            return EditResult(message=EDIT_HELP)

        if lowered.startswith("list_system_lore"):
            return self._list_lore(COLLECTION_SYSTEM, raw)
        if lowered.startswith("view_system_lore"):
            return self._view_lore(COLLECTION_SYSTEM, raw)
        if lowered.startswith("add_system_lore"):
            return self._add_system_lore(raw)
        if lowered.startswith("create_system_lore"):
            return self._create_system_lore(raw)
        if lowered == "list_drafts":
            return self._list_drafts()
        if lowered.startswith("view_draft"):
            return self._view_draft(raw)
        if lowered.startswith("approve_draft"):
            return self._approve_draft(raw)
        if lowered.startswith("reject_draft"):
            return self._reject_draft(raw)

        if lowered.startswith("list_room_lore"):
            return self._list_lore(COLLECTION_ROOM, raw)
        if lowered.startswith("view_room_lore"):
            return self._view_lore(COLLECTION_ROOM, raw)
        if lowered.startswith("add_room_lore"):
            return self._add_room_lore(raw)

        if lowered.startswith("list_item_lore"):
            return self._list_lore(COLLECTION_ITEM, raw)
        if lowered.startswith("view_item_lore"):
            return self._view_lore(COLLECTION_ITEM, raw)
        if lowered.startswith("add_item_lore"):
            return self._add_item_lore(raw)

        return EditResult(
            ok=False,
            message="Unknown edit_mode command. Type 'help' for the constrained command set.",
        )

    def _parse_search(self, raw: str) -> str | None:
        match = re.search(r"search=(\S+)", raw, flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _preview(self, text: str, limit: int = 50) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1] + "…"

    def _list_lore(self, collection: str, raw: str) -> EditResult:
        search = self._parse_search(raw)
        entries = self.lore.list_entries(collection, search=search)
        if not entries:
            return EditResult(message=f"No {collection} entries found.")
        lines = [f"{collection} ({len(entries)}):"]
        for key, text in entries:
            lines.append(f"- {key}: {self._preview(text)}")
        return EditResult(message="\n".join(lines))

    def _view_lore(self, collection: str, raw: str) -> EditResult:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            return EditResult(ok=False, message="Usage: view_*_lore <key>")
        key = parts[1].strip()
        text = self.lore.get_lore(collection, key)
        if text is None:
            return EditResult(ok=False, message=f"No lore found for key '{key}'.")
        return EditResult(message=f"[{collection}] {key}\n{text}")

    def _split_key_and_text(self, command: str, raw: str) -> tuple[str, str] | EditResult:
        body = raw[len(command) :].strip()
        if "|" in body:
            key, text = body.split("|", 1)
            key = key.strip()
            text = text.strip()
        else:
            try:
                tokens = shlex.split(body)
            except ValueError as exc:
                return EditResult(ok=False, message=f"Could not parse command: {exc}")
            if len(tokens) < 2:
                return EditResult(
                    ok=False,
                    message=f"Usage: {command} <key-or-id> | <text...>",
                )
            key = tokens[0]
            text = " ".join(tokens[1:]).strip()
        if not key or not text:
            return EditResult(ok=False, message="Both key/id and text are required.")
        return key, text

    def _add_system_lore(self, raw: str) -> EditResult:
        parsed = self._split_key_and_text("add_system_lore", raw)
        if isinstance(parsed, EditResult):
            return parsed
        key, text = parsed
        self.lore.upsert_lore(COLLECTION_SYSTEM, key, text)
        self.world.upsert_lore_key_ref("system", "world", key)
        self._logger.info("Admin added system lore key=%s", key)
        return EditResult(
            message=(
                f"Saved canonical system lore '{key}'. "
                "This was an explicit admin write (not a generated draft)."
            )
        )

    def _create_system_lore(self, raw: str) -> EditResult:
        prompt = raw[len("create_system_lore") :].strip()
        if not prompt:
            return EditResult(
                ok=False,
                message="Usage: create_system_lore <prompt...>",
            )

        existing = self.lore.list_entries(COLLECTION_SYSTEM)
        grounding = "\n\n".join(
            f"KEY: {key}\nTEXT: {text}" for key, text in existing
        ) or "(no existing system lore)"

        user_message = (
            "Create a reviewable system lore draft grounded in the existing system lore.\n"
            "Return only the draft lore text. Do not claim it is saved.\n"
            f"Admin prompt: {prompt}\n\n"
            f"Existing system lore:\n{grounding}"
        )
        try:
            response = self.llm.complete(
                system=self.system_prompt,
                messages=[ChatMessage(role="user", content=user_message)],
                tools=None,
            )
            draft_text = response.text.strip()
        except Exception as exc:
            self._logger.exception("Draft generation failed: %s", exc)
            return EditResult(
                ok=False,
                message=f"Draft generation failed: {exc}",
            )

        if not draft_text:
            return EditResult(ok=False, message="Model returned an empty draft.")

        slug = re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_")[:40] or "draft"
        proposed_key = f"system:draft_{slug}"
        draft = self.drafts.create_draft(
            collection_name=COLLECTION_SYSTEM,
            proposed_key=proposed_key,
            draft_text=draft_text,
            prompt=prompt,
            created_by_user_id=self.auth.user.id,
        )
        self._logger.info("Created pending system lore draft id=%s", draft.id)
        return EditResult(
            message=(
                f"Created pending draft #{draft.id} for key '{draft.proposed_key}'.\n"
                "This is NOT canonical yet. Review with view_draft, then "
                "approve_draft or reject_draft.\n\n"
                f"{draft.draft_text}"
            )
        )

    def _list_drafts(self) -> EditResult:
        drafts = self.drafts.list_drafts(status="pending")
        if not drafts:
            return EditResult(message="No pending drafts.")
        lines = ["Pending drafts:"]
        for draft in drafts:
            lines.append(
                f"- #{draft.id} [{draft.collection_name}] {draft.proposed_key}: "
                f"{self._preview(draft.draft_text)}"
            )
        return EditResult(message="\n".join(lines))

    def _view_draft(self, raw: str) -> EditResult:
        parts = raw.split()
        if len(parts) < 2 or not parts[1].isdigit():
            return EditResult(ok=False, message="Usage: view_draft <id>")
        draft = self.drafts.get_draft(int(parts[1]))
        if draft is None:
            return EditResult(ok=False, message="Draft not found.")
        return EditResult(
            message=(
                f"Draft #{draft.id} status={draft.status}\n"
                f"collection={draft.collection_name}\n"
                f"proposed_key={draft.proposed_key}\n"
                f"prompt={draft.prompt or '(none)'}\n\n"
                f"{draft.draft_text}"
            )
        )

    def _approve_draft(self, raw: str) -> EditResult:
        parts = raw.split()
        if len(parts) < 2 or not parts[1].isdigit():
            return EditResult(ok=False, message="Usage: approve_draft <id>")
        draft_id = int(parts[1])
        draft = self.drafts.get_draft(draft_id)
        if draft is None:
            return EditResult(ok=False, message="Draft not found.")
        if draft.status != "pending":
            return EditResult(
                ok=False,
                message=f"Draft #{draft_id} is {draft.status}, not pending.",
            )

        self.lore.upsert_lore(
            draft.collection_name,
            draft.proposed_key,
            draft.draft_text,
        )
        if draft.collection_name == COLLECTION_SYSTEM:
            self.world.upsert_lore_key_ref("system", "world", draft.proposed_key)
        invalidated = self._invalidate_for_lore_key(
            draft.collection_name,
            draft.proposed_key,
        )
        self.drafts.set_status(draft_id, "approved")
        self._logger.info("Approved draft id=%s key=%s", draft_id, draft.proposed_key)
        extra = f" Invalidated presentation for: {invalidated}." if invalidated else ""
        return EditResult(
            message=(
                f"Approved draft #{draft_id}. Canon saved as '{draft.proposed_key}'."
                f"{extra}"
            )
        )

    def _reject_draft(self, raw: str) -> EditResult:
        parts = raw.split()
        if len(parts) < 2 or not parts[1].isdigit():
            return EditResult(ok=False, message="Usage: reject_draft <id>")
        draft_id = int(parts[1])
        draft = self.drafts.get_draft(draft_id)
        if draft is None:
            return EditResult(ok=False, message="Draft not found.")
        if draft.status != "pending":
            return EditResult(
                ok=False,
                message=f"Draft #{draft_id} is {draft.status}, not pending.",
            )
        self.drafts.set_status(draft_id, "rejected")
        return EditResult(
            message=f"Rejected draft #{draft_id}. Nothing was written to canon."
        )

    def _add_room_lore(self, raw: str) -> EditResult:
        parsed = self._split_key_and_text("add_room_lore", raw)
        if isinstance(parsed, EditResult):
            return parsed
        room_id, text = parsed
        room = self.world.get_room(room_id)
        if room is None:
            return EditResult(
                ok=False,
                message=(
                    f"Room '{room_id}' is not in SQLite. "
                    "World Builder / structural seeding is out of scope for edit_mode."
                ),
            )
        self.lore.upsert_lore(COLLECTION_ROOM, room.lore_key, text)
        self.world.upsert_lore_key_ref("room", room.room_id, room.lore_key)
        self.world.invalidate_room_presentation(room.room_id)
        self._logger.info(
            "Admin updated room lore room_id=%s key=%s",
            room.room_id,
            room.lore_key,
        )
        return EditResult(
            message=(
                f"Saved canonical room lore for '{room.room_id}' "
                f"(key={room.lore_key}). "
                "Presentation state invalidated for this room."
            )
        )

    def _add_item_lore(self, raw: str) -> EditResult:
        parsed = self._split_key_and_text("add_item_lore", raw)
        if isinstance(parsed, EditResult):
            return parsed
        item_id, text = parsed
        definition = self.world.get_item_definition(item_id)
        if definition is None:
            return EditResult(
                ok=False,
                message=(
                    f"Item definition '{item_id}' is not in SQLite. "
                    "Item instances/inventories remain runtime state and were not changed."
                ),
            )
        self.lore.upsert_lore(COLLECTION_ITEM, definition.lore_key, text)
        self.world.upsert_lore_key_ref(
            "item_definition",
            definition.item_id,
            definition.lore_key,
        )
        self.world.invalidate_item_presentation_for_definition(definition.item_id)
        self._logger.info(
            "Admin updated item lore item_id=%s key=%s",
            definition.item_id,
            definition.lore_key,
        )
        return EditResult(
            message=(
                f"Saved canonical item lore for definition '{definition.item_id}' "
                f"(key={definition.lore_key}). "
                "Item instances/inventories were not modified. "
                "Presentation state invalidated for affected instances."
            )
        )

    def _invalidate_for_lore_key(
        self,
        collection_name: str,
        lore_key: str,
    ) -> str:
        if collection_name == COLLECTION_ROOM:
            rooms = self.world.find_rooms_by_lore_key(lore_key)
            for room in rooms:
                self.world.invalidate_room_presentation(room.room_id)
            return ", ".join(room.room_id for room in rooms)
        if collection_name == COLLECTION_ITEM:
            definitions = self.world.find_item_definitions_by_lore_key(lore_key)
            for definition in definitions:
                self.world.invalidate_item_presentation_for_definition(
                    definition.item_id
                )
            return ", ".join(definition.item_id for definition in definitions)
        return ""
