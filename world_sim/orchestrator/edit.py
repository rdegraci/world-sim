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
    COLLECTION_NPC,
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)
from world_sim.models import AuthContext
from world_sim.orchestrator.presentation import npc_canonical_description
from world_sim.orchestrator.prompts import compose_edit_system_prompt
from world_sim.utils.logger import get_logger

EDIT_HELP = """\
edit_mode commands (admin only):
  help
  mode play                 Leave edit_mode and return to play_mode

  System lore:
    list_system_lore [search=...]
    view_system_lore <key>
    add_system_lore <key> | <text...>
    create_system_lore <prompt...>
    delete_system_lore <key>

  Room lore (existing rooms only — new rooms/exits: world-builder):
    list_rooms [search=...]
    list_room_lore [room_id=...] [search=...]
    view_room_lore <key>
    add_room_lore <room_id> | <text...>
    create_room_lore <room_id> <prompt...>
    delete_room_lore <key>

  Item lore (existing definitions only — new defs/placements: world-builder):
    list_items [search=...]
    list_item_lore [item_id=...] [search=...]
    view_item_lore <key>
    add_item_lore <item_id> | <text...>
    create_item_lore <item_id> <prompt...>
    delete_item_lore <key>

  NPCs:
    list_npcs [search=...]
    view_npc <npc_id>
    add_npc_lore <npc_id> | <text...>
    add_npc <npc_id> | <name> | <lore_key>[,<lore_key>...] [--in <room>]
    create_npc <prompt...>
    edit_npc <npc_id> | name=<new name>
    delete_npc <npc_id>

  Drafts (LLM-assisted; not canon until approve):
    list_drafts
    view_draft <id>
    approve_draft <id>
    reject_draft <id>

Notes:
  - create_* stores a pending draft only; approve_draft makes it canonical.
  - add_* is an explicit admin write (no draft).
  - Canon edits invalidate recap + full-description-seen for affected entities.
  - Bulk rooms/links/placements stay in world-builder.
"""


@dataclass(frozen=True)
class EditResult:
    message: str
    ok: bool = True


class EditAccessError(Exception):
    """Raised when a non-admin attempts edit_mode operations."""


class EditOrchestrator:
    """Admin canon operations with review-before-save for LLM-assisted drafts."""

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
        if lowered.startswith("delete_system_lore"):
            return self._delete_system_lore(raw)

        if lowered == "list_drafts":
            return self._list_drafts()
        if lowered.startswith("view_draft"):
            return self._view_draft(raw)
        if lowered.startswith("approve_draft"):
            return self._approve_draft(raw)
        if lowered.startswith("reject_draft"):
            return self._reject_draft(raw)

        if lowered.startswith("list_rooms"):
            return self._list_rooms(raw)
        if lowered.startswith("list_room_lore"):
            return self._list_lore(COLLECTION_ROOM, raw)
        if lowered.startswith("view_room_lore"):
            return self._view_lore(COLLECTION_ROOM, raw)
        if lowered.startswith("add_room_lore"):
            return self._add_room_lore(raw)
        if lowered.startswith("create_room_lore"):
            return self._create_room_lore(raw)
        if lowered.startswith("delete_room_lore"):
            return self._delete_room_lore(raw)

        if lowered.startswith("list_items"):
            return self._list_items(raw)
        if lowered.startswith("list_item_lore"):
            return self._list_lore(COLLECTION_ITEM, raw)
        if lowered.startswith("view_item_lore"):
            return self._view_lore(COLLECTION_ITEM, raw)
        if lowered.startswith("add_item_lore"):
            return self._add_item_lore(raw)
        if lowered.startswith("create_item_lore"):
            return self._create_item_lore(raw)
        if lowered.startswith("delete_item_lore"):
            return self._delete_item_lore(raw)

        if lowered.startswith("list_npcs"):
            return self._list_npcs(raw)
        if lowered.startswith("view_npc"):
            return self._view_npc(raw)
        if lowered.startswith("add_npc_lore"):
            return self._add_npc_lore(raw)
        if lowered.startswith("add_npc"):
            return self._add_npc(raw)
        if lowered.startswith("create_npc"):
            return self._create_npc(raw)
        if lowered.startswith("edit_npc"):
            return self._edit_npc(raw)
        if lowered.startswith("delete_npc"):
            return self._delete_npc(raw)

        return EditResult(
            ok=False,
            message="Unknown edit_mode command. Type 'help' for the constrained command set.",
        )

    def _parse_search(self, raw: str) -> str | None:
        match = re.search(r"search=(\S+)", raw, flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _parse_named(self, raw: str, name: str) -> str | None:
        match = re.search(rf"{name}=(\S+)", raw, flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _preview(self, text: str, limit: int = 50) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1] + "…"

    def _slug(self, text: str, *, max_len: int = 40) -> str:
        return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:max_len] or "draft"

    def _list_lore(self, collection: str, raw: str) -> EditResult:
        search = self._parse_search(raw)
        entries = self.lore.list_entries(collection, search=search)
        room_id = self._parse_named(raw, "room_id")
        item_id = self._parse_named(raw, "item_id")
        if room_id:
            room = self.world.get_room(room_id)
            if room is None:
                return EditResult(ok=False, message=f"Room '{room_id}' not found.")
            entries = [(key, text) for key, text in entries if key == room.lore_key]
        if item_id:
            definition = self.world.get_item_definition(item_id)
            if definition is None:
                return EditResult(
                    ok=False, message=f"Item definition '{item_id}' not found."
                )
            entries = [
                (key, text) for key, text in entries if key == definition.lore_key
            ]
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

    def _list_rooms(self, raw: str) -> EditResult:
        search = self._parse_search(raw)
        rooms = self.world.list_rooms()
        if search:
            needle = search.lower()
            rooms = [
                room
                for room in rooms
                if needle in room.room_id.lower()
                or needle in room.name.lower()
                or needle in room.lore_key.lower()
            ]
        if not rooms:
            return EditResult(message="No rooms found.")
        lines = [f"rooms ({len(rooms)}):"]
        for room in rooms:
            lines.append(f"- {room.room_id}: {room.name} lore={room.lore_key}")
        return EditResult(message="\n".join(lines))

    def _list_items(self, raw: str) -> EditResult:
        search = self._parse_search(raw)
        items = self.world.list_item_definitions()
        if search:
            needle = search.lower()
            items = [
                item
                for item in items
                if needle in item.item_id.lower()
                or needle in item.name.lower()
                or needle in item.lore_key.lower()
            ]
        if not items:
            return EditResult(message="No item definitions found.")
        lines = [f"item_definitions ({len(items)}):"]
        for item in items:
            lines.append(f"- {item.item_id}: {item.name} lore={item.lore_key}")
        return EditResult(message="\n".join(lines))

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
            return EditResult(ok=False, message="Usage: create_system_lore <prompt...>")
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
        draft_text = self._generate_draft_text(user_message)
        if isinstance(draft_text, EditResult):
            return draft_text
        proposed_key = f"system:draft_{self._slug(prompt)}"
        return self._store_pending_draft(
            collection_name=COLLECTION_SYSTEM,
            proposed_key=proposed_key,
            draft_text=draft_text,
            prompt=prompt,
        )

    def _create_room_lore(self, raw: str) -> EditResult:
        body = raw[len("create_room_lore") :].strip()
        parts = body.split(maxsplit=1)
        if len(parts) < 2:
            return EditResult(
                ok=False,
                message="Usage: create_room_lore <room_id> <prompt...>",
            )
        room_id, prompt = parts[0].strip(), parts[1].strip()
        room = self.world.get_room(room_id)
        if room is None:
            return EditResult(
                ok=False,
                message=(
                    f"Room '{room_id}' is not in SQLite. "
                    "Create structure with world-builder, then revise lore here."
                ),
            )
        system_bits = self._grounding_block(COLLECTION_SYSTEM, limit=8)
        room_bits = self._grounding_block(COLLECTION_ROOM, limit=12)
        current = self.lore.get_lore(COLLECTION_ROOM, room.lore_key) or "(none)"
        user_message = (
            "Create a reviewable room lore draft grounded in system lore and room lore.\n"
            "Return only the replacement room lore text. Do not claim it is saved.\n"
            f"Target room_id: {room.room_id}\n"
            f"Target lore_key: {room.lore_key}\n"
            f"Current room lore:\n{current}\n\n"
            f"Admin prompt: {prompt}\n\n"
            f"Existing system lore:\n{system_bits}\n\n"
            f"Existing room lore:\n{room_bits}"
        )
        draft_text = self._generate_draft_text(user_message)
        if isinstance(draft_text, EditResult):
            return draft_text
        return self._store_pending_draft(
            collection_name=COLLECTION_ROOM,
            proposed_key=room.lore_key,
            draft_text=draft_text,
            prompt=f"room_id={room.room_id}|{prompt}",
        )

    def _create_item_lore(self, raw: str) -> EditResult:
        body = raw[len("create_item_lore") :].strip()
        parts = body.split(maxsplit=1)
        if len(parts) < 2:
            return EditResult(
                ok=False,
                message="Usage: create_item_lore <item_id> <prompt...>",
            )
        item_id, prompt = parts[0].strip(), parts[1].strip()
        definition = self.world.get_item_definition(item_id)
        if definition is None:
            return EditResult(
                ok=False,
                message=(
                    f"Item definition '{item_id}' is not in SQLite. "
                    "Create definitions with world-builder, then revise lore here."
                ),
            )
        system_bits = self._grounding_block(COLLECTION_SYSTEM, limit=6)
        item_bits = self._grounding_block(COLLECTION_ITEM, limit=10)
        current = self.lore.get_lore(COLLECTION_ITEM, definition.lore_key) or "(none)"
        user_message = (
            "Create a reviewable item lore draft grounded in system lore and item lore.\n"
            "Return only the replacement item lore text. Do not claim it is saved.\n"
            f"Target item_id: {definition.item_id}\n"
            f"Target lore_key: {definition.lore_key}\n"
            f"Current item lore:\n{current}\n\n"
            f"Admin prompt: {prompt}\n\n"
            f"Existing system lore:\n{system_bits}\n\n"
            f"Existing item lore:\n{item_bits}"
        )
        draft_text = self._generate_draft_text(user_message)
        if isinstance(draft_text, EditResult):
            return draft_text
        return self._store_pending_draft(
            collection_name=COLLECTION_ITEM,
            proposed_key=definition.lore_key,
            draft_text=draft_text,
            prompt=f"item_id={definition.item_id}|{prompt}",
        )

    def _create_npc(self, raw: str) -> EditResult:
        prompt = raw[len("create_npc") :].strip()
        if not prompt:
            return EditResult(ok=False, message="Usage: create_npc <prompt...>")
        system_bits = self._grounding_block(COLLECTION_SYSTEM, limit=6)
        room_bits = self._grounding_block(COLLECTION_ROOM, limit=8)
        npc_bits = self._grounding_block(COLLECTION_NPC, limit=8)
        user_message = (
            "Create a reviewable NPC draft grounded in system, room, and NPC lore.\n"
            "Return exactly this format (no other commentary):\n"
            "NPC_ID: <snake_case_id>\n"
            "NAME: <display name>\n"
            "DESCRIPTION:\n"
            "<canonical description text>\n"
            "Do not claim it is saved.\n"
            f"Admin prompt: {prompt}\n\n"
            f"Existing system lore:\n{system_bits}\n\n"
            f"Existing room lore:\n{room_bits}\n\n"
            f"Existing NPC lore:\n{npc_bits}"
        )
        draft_text = self._generate_draft_text(user_message)
        if isinstance(draft_text, EditResult):
            return draft_text
        parsed = self._parse_npc_draft(draft_text)
        if parsed is None:
            return EditResult(
                ok=False,
                message=(
                    "Draft was not in the required NPC_ID/NAME/DESCRIPTION format. "
                    "Nothing was stored."
                ),
            )
        npc_id, name, description = parsed
        proposed_key = f"npc:{npc_id}:description"
        stored = (
            f"NPC_ID: {npc_id}\n"
            f"NAME: {name}\n"
            f"DESCRIPTION:\n{description}"
        )
        return self._store_pending_draft(
            collection_name=COLLECTION_NPC,
            proposed_key=proposed_key,
            draft_text=stored,
            prompt=prompt,
        )

    def _generate_draft_text(self, user_message: str) -> str | EditResult:
        try:
            response = self.llm.complete(
                system=self.system_prompt,
                messages=[ChatMessage(role="user", content=user_message)],
                tools=None,
            )
            draft_text = response.text.strip()
        except Exception as exc:
            self._logger.exception("Draft generation failed: %s", exc)
            return EditResult(ok=False, message=f"Draft generation failed: {exc}")
        if not draft_text:
            return EditResult(ok=False, message="Model returned an empty draft.")
        return draft_text

    def _store_pending_draft(
        self,
        *,
        collection_name: str,
        proposed_key: str,
        draft_text: str,
        prompt: str,
    ) -> EditResult:
        draft = self.drafts.create_draft(
            collection_name=collection_name,
            proposed_key=proposed_key,
            draft_text=draft_text,
            prompt=prompt,
            created_by_user_id=self.auth.user.id,
        )
        self._logger.info(
            "Created pending draft id=%s collection=%s key=%s",
            draft.id,
            collection_name,
            proposed_key,
        )
        return EditResult(
            message=(
                f"Created pending draft #{draft.id} for key '{draft.proposed_key}'.\n"
                "This is NOT canonical yet. Review with view_draft, then "
                "approve_draft or reject_draft.\n\n"
                f"{draft.draft_text}"
            )
        )

    def _grounding_block(self, collection: str, *, limit: int) -> str:
        entries = self.lore.list_entries(collection)[:limit]
        if not entries:
            return f"(no existing {collection})"
        return "\n\n".join(f"KEY: {key}\nTEXT: {text}" for key, text in entries)

    @staticmethod
    def _parse_npc_draft(text: str) -> tuple[str, str, str] | None:
        npc_id_match = re.search(r"^NPC_ID:\s*(\S+)\s*$", text, flags=re.MULTILINE)
        name_match = re.search(r"^NAME:\s*(.+)\s*$", text, flags=re.MULTILINE)
        desc_match = re.search(
            r"^DESCRIPTION:\s*\n?(.*)\Z",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not npc_id_match or not name_match or not desc_match:
            return None
        npc_id = re.sub(r"[^a-z0-9_]+", "_", npc_id_match.group(1).lower()).strip("_")
        name = name_match.group(1).strip()
        description = desc_match.group(1).strip()
        if not npc_id or not name or not description:
            return None
        return npc_id, name, description

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

        if draft.collection_name == COLLECTION_NPC:
            parsed = self._parse_npc_draft(draft.draft_text)
            if parsed is None:
                return EditResult(
                    ok=False,
                    message="NPC draft is malformed; cannot approve.",
                )
            npc_id, name, description = parsed
            lore_key = draft.proposed_key or f"npc:{npc_id}:description"
            self.lore.upsert_lore(COLLECTION_NPC, lore_key, description)
            existing = self.world.get_npc(npc_id)
            lore_keys = [lore_key]
            if existing:
                for key in existing.npc_lore:
                    if key not in lore_keys:
                        lore_keys.append(key)
            self.world.upsert_npc(
                npc_id,
                name,
                npc_lore=lore_keys,
                current_room_id=existing.current_room_id if existing else None,
                condition=existing.condition if existing else None,
            )
            invalidated = self._invalidate_for_lore_key(COLLECTION_NPC, lore_key)
            self.drafts.set_status(draft_id, "approved")
            self._logger.info(
                "Approved NPC draft id=%s npc_id=%s key=%s",
                draft_id,
                npc_id,
                lore_key,
            )
            extra = f" Invalidated presentation for: {invalidated}." if invalidated else ""
            return EditResult(
                message=(
                    f"Approved draft #{draft_id}. Canon NPC '{npc_id}' saved "
                    f"(key={lore_key}).{extra}"
                )
            )

        self.lore.upsert_lore(
            draft.collection_name,
            draft.proposed_key,
            draft.draft_text,
        )
        if draft.collection_name == COLLECTION_SYSTEM:
            self.world.upsert_lore_key_ref("system", "world", draft.proposed_key)
        elif draft.collection_name == COLLECTION_ROOM:
            for room in self.world.find_rooms_by_lore_key(draft.proposed_key):
                self.world.upsert_lore_key_ref("room", room.room_id, draft.proposed_key)
        elif draft.collection_name == COLLECTION_ITEM:
            for definition in self.world.find_item_definitions_by_lore_key(
                draft.proposed_key
            ):
                self.world.upsert_lore_key_ref(
                    "item_definition",
                    definition.item_id,
                    draft.proposed_key,
                )

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

    def _list_npcs(self, raw: str) -> EditResult:
        search = self._parse_search(raw)
        npcs = self.world.list_npcs()
        if search:
            needle = search.lower()
            npcs = [
                npc
                for npc in npcs
                if needle in npc.npc_id.lower() or needle in npc.name.lower()
            ]
        if not npcs:
            return EditResult(message="No NPCs found.")
        lines = [f"npcs ({len(npcs)}):"]
        for npc in npcs:
            lines.append(
                f"- {npc.npc_id}: {npc.name} room={npc.current_room_id} "
                f"lore={npc.npc_lore}"
            )
        return EditResult(message="\n".join(lines))

    def _view_npc(self, raw: str) -> EditResult:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            return EditResult(ok=False, message="Usage: view_npc <npc_id>")
        npc = self.world.get_npc(parts[1].strip())
        if npc is None:
            return EditResult(ok=False, message="NPC not found.")
        description = npc_canonical_description(self.world, self.lore, npc.npc_id)
        return EditResult(
            message=(
                f"npc_id={npc.npc_id}\n"
                f"name={npc.name}\n"
                f"current_room_id={npc.current_room_id}\n"
                f"condition={npc.condition}\n"
                f"npc_lore={npc.npc_lore}\n\n"
                f"{description}"
            )
        )

    def _add_npc_lore(self, raw: str) -> EditResult:
        parsed = self._split_key_and_text("add_npc_lore", raw)
        if isinstance(parsed, EditResult):
            return parsed
        npc_id, text = parsed
        npc = self.world.get_npc(npc_id)
        if npc is None:
            return EditResult(
                ok=False,
                message=(
                    f"NPC '{npc_id}' is not in SQLite. "
                    "Use add_npc or create_npc (draft→approve), or seed via world-builder."
                ),
            )
        primary_key = npc.npc_lore[0] if npc.npc_lore else f"npc:{npc_id}:description"
        lore_keys = list(npc.npc_lore) or [primary_key]
        if primary_key not in lore_keys:
            lore_keys.insert(0, primary_key)
        self.lore.upsert_lore(COLLECTION_NPC, primary_key, text)
        self.world.upsert_npc(
            npc.npc_id,
            npc.name,
            npc_lore=lore_keys,
            current_room_id=npc.current_room_id,
            condition=npc.condition,
        )
        self.world.invalidate_npc_presentation(npc.npc_id)
        self._logger.info(
            "Admin updated NPC lore npc_id=%s key=%s",
            npc.npc_id,
            primary_key,
        )
        return EditResult(
            message=(
                f"Saved canonical NPC lore for '{npc.npc_id}' (key={primary_key}). "
                "NPC inventory/runtime placement were not modified. "
                "Presentation state invalidated for this NPC."
            )
        )

    def _add_npc(self, raw: str) -> EditResult:
        body = raw[len("add_npc") :].strip()
        room_id = None
        if "--in" in body:
            before, after = body.split("--in", 1)
            body = before.strip()
            room_id = after.strip() or None
        parts = [part.strip() for part in body.split("|")]
        if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
            return EditResult(
                ok=False,
                message=(
                    "Usage: add_npc <npc_id> | <name> | <lore_key>[,<lore_key>...] "
                    "[--in <room_id>]"
                ),
            )
        npc_id, name, lore_part = parts[0], parts[1], parts[2]
        lore_keys = [key.strip() for key in lore_part.split(",") if key.strip()]
        if not lore_keys:
            return EditResult(ok=False, message="At least one lore_key is required.")
        missing = [
            key
            for key in lore_keys
            if self.lore.get_lore(COLLECTION_NPC, key) is None
        ]
        if missing:
            return EditResult(
                ok=False,
                message=(
                    "Missing approved NPC lore keys (fail closed): "
                    + ", ".join(missing)
                    + ". Upsert lore first (world-builder upsert_lore or approve a create_npc draft)."
                ),
            )
        if room_id and self.world.get_room(room_id) is None:
            return EditResult(ok=False, message=f"Room '{room_id}' not found.")
        existing = self.world.get_npc(npc_id)
        self.world.upsert_npc(
            npc_id,
            name,
            npc_lore=lore_keys,
            current_room_id=room_id
            if room_id is not None
            else (existing.current_room_id if existing else None),
            condition=existing.condition if existing else None,
        )
        self.world.invalidate_npc_presentation(npc_id)
        return EditResult(
            message=(
                f"Saved canonical NPC '{npc_id}' with lore keys {lore_keys}. "
                "Presentation state invalidated."
            )
        )

    def _edit_npc(self, raw: str) -> EditResult:
        body = raw[len("edit_npc") :].strip()
        if "|" not in body:
            return EditResult(
                ok=False,
                message="Usage: edit_npc <npc_id> | name=<new name>",
            )
        npc_id, rest = body.split("|", 1)
        npc_id = npc_id.strip()
        rest = rest.strip()
        npc = self.world.get_npc(npc_id)
        if npc is None:
            return EditResult(ok=False, message=f"NPC '{npc_id}' not found.")
        name_match = re.match(r"name\s*=\s*(.+)$", rest, flags=re.IGNORECASE)
        if not name_match:
            return EditResult(
                ok=False,
                message="Usage: edit_npc <npc_id> | name=<new name>",
            )
        new_name = name_match.group(1).strip()
        if not new_name:
            return EditResult(ok=False, message="New name must be non-empty.")
        self.world.upsert_npc(
            npc.npc_id,
            new_name,
            npc_lore=list(npc.npc_lore),
            current_room_id=npc.current_room_id,
            condition=npc.condition,
        )
        self.world.invalidate_npc_presentation(npc.npc_id)
        return EditResult(
            message=(
                f"Updated NPC '{npc.npc_id}' name to '{new_name}'. "
                "Presentation state invalidated."
            )
        )

    def _delete_npc(self, raw: str) -> EditResult:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            return EditResult(ok=False, message="Usage: delete_npc <npc_id>")
        npc_id = parts[1].strip()
        npc = self.world.get_npc(npc_id)
        if npc is None:
            return EditResult(ok=False, message=f"NPC '{npc_id}' not found.")
        with self.world.connection:
            self.world.connection.execute(
                "DELETE FROM npcs WHERE npc_id = ?",
                (npc_id,),
            )
        self.world.invalidate_npc_presentation(npc_id)
        return EditResult(
            message=(
                f"Deleted NPC record '{npc_id}'. Chroma NPC lore keys were left in place "
                f"({npc.npc_lore}). Use world-builder validate_world to spot unused lore."
            )
        )

    def _delete_system_lore(self, raw: str) -> EditResult:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            return EditResult(ok=False, message="Usage: delete_system_lore <key>")
        return self._delete_chroma_key(COLLECTION_SYSTEM, parts[1].strip())

    def _delete_room_lore(self, raw: str) -> EditResult:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            return EditResult(ok=False, message="Usage: delete_room_lore <key>")
        key = parts[1].strip()
        linked = self.world.find_rooms_by_lore_key(key)
        if linked:
            ids = ", ".join(room.room_id for room in linked)
            return EditResult(
                ok=False,
                message=(
                    f"Refusing to delete '{key}': still linked from room(s) {ids}. "
                    "Update or remove those rooms via world-builder first."
                ),
            )
        return self._delete_chroma_key(COLLECTION_ROOM, key)

    def _delete_item_lore(self, raw: str) -> EditResult:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            return EditResult(ok=False, message="Usage: delete_item_lore <key>")
        key = parts[1].strip()
        linked = self.world.find_item_definitions_by_lore_key(key)
        if linked:
            ids = ", ".join(item.item_id for item in linked)
            return EditResult(
                ok=False,
                message=(
                    f"Refusing to delete '{key}': still linked from item definition(s) "
                    f"{ids}."
                ),
            )
        return self._delete_chroma_key(COLLECTION_ITEM, key)

    def _delete_chroma_key(self, collection: str, key: str) -> EditResult:
        if not self.lore.delete_lore(collection, key):
            return EditResult(ok=False, message=f"No lore found for key '{key}'.")
        self._logger.info("Admin deleted lore collection=%s key=%s", collection, key)
        return EditResult(message=f"Deleted canonical lore '{key}' from {collection}.")

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
        if collection_name == COLLECTION_NPC:
            affected: list[str] = []
            for npc in self.world.list_npcs():
                if lore_key in npc.npc_lore:
                    self.world.invalidate_npc_presentation(npc.npc_id)
                    affected.append(npc.npc_id)
            return ", ".join(affected)
        return ""
