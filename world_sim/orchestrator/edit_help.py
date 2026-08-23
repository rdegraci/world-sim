"""Per-command help text for admin edit_mode (usage, examples, notes)."""

from __future__ import annotations

# Alias names resolve to canonical help keys.
HELP_ALIASES: dict[str, str] = {
    "edit_system_lore": "add_system_lore",
    "edit_room_lore": "add_room_lore",
    "edit_item_lore": "add_item_lore",
    "edit_npc_lore": "add_npc_lore",
    "append_npc_lore": "revise_npc_lore",
}

EDIT_COMMAND_HELP: dict[str, str] = {
    "help": """\
help — list all edit_mode commands or show one command in detail

Usage:
  help
  help <command>

Examples:
  help
  help add_npc
  help approve_draft

Notes:
  - ? alone is the same as help; ? <command> also works.
  - Per-command pages include copy-paste examples.
""",
    "mode": """\
mode play — leave edit_mode and return to play_mode

Usage:
  mode play

Examples:
  mode play

Notes:
  - Run from edit> or chat>; session shell handles the mode switch.
  - edit_mode and chat_mode are admin-only.
""",
    "list_system_lore": """\
list_system_lore — list system lore keys in Chroma

Usage:
  list_system_lore [search=<text>]

Examples:
  list_system_lore
  list_system_lore search=manor

Notes:
  - Read-only; does not change canon.
""",
    "view_system_lore": """\
view_system_lore — show full text for one system lore key

Usage:
  view_system_lore <key>

Examples:
  view_system_lore system:quiet_manor:overview

Notes:
  - Key must exist in Chroma.
""",
    "add_system_lore": """\
add_system_lore — write or replace system lore in Chroma (immediate canon)

Usage:
  add_system_lore <key> | <text...>

Examples:
  add_system_lore system:quiet_manor:bell | The manor bell marks evening in the halls.

Notes:
  - Immediate canon write (no draft). Alias: edit_system_lore.
  - Invalidates presentation for entities tied to that lore.
""",
    "create_system_lore": """\
create_system_lore — LLM draft for system lore (not canon until approve_draft)

Usage:
  create_system_lore <prompt...>

Examples:
  create_system_lore A note about the manor evening bell
  list_drafts
  view_draft 1
  approve_draft 1

Notes:
  - Draft only until approve_draft.
  - For direct writes without the LLM, use add_system_lore.
""",
    "delete_system_lore": """\
delete_system_lore — remove a system lore key from Chroma

Usage:
  delete_system_lore <key>

Examples:
  delete_system_lore system:quiet_manor:bell

Notes:
  - Fail closed when deletion would break required refs; check the error message.
""",
    "list_rooms": """\
list_rooms — list rooms in SQLite (id, name, lore_key)

Usage:
  list_rooms [search=<text>]

Examples:
  list_rooms
  list_rooms search=study

Notes:
  - Structure only; new rooms and exits are world-builder work.
""",
    "list_room_lore": """\
list_room_lore — list room lore keys in Chroma

Usage:
  list_room_lore [room_id=<id>] [search=<text>]

Examples:
  list_room_lore
  list_room_lore room_id=foyer
  list_room_lore search=hall

Notes:
  - Read-only listing; room must exist for room_id= filter on SQLite refs.
""",
    "view_room_lore": """\
view_room_lore — show full text for one room lore key

Usage:
  view_room_lore <key>

Examples:
  view_room_lore room:foyer:description

Notes:
  - Key must exist in Chroma.
""",
    "add_room_lore": """\
add_room_lore — write or replace room lore for an existing room (immediate canon)

Usage:
  add_room_lore <room_id> | <text...>

Examples:
  add_room_lore foyer | The foyer holds damp coats by the door and worn stone flags.
  add_room_lore study | The study smells of ink and old paper.

Notes:
  - Room must already exist in SQLite. Alias: edit_room_lore.
  - Immediate write (no draft). Invalidates room presentation for all players.
""",
    "create_room_lore": """\
create_room_lore — LLM draft for room lore (not canon until approve_draft)

Usage:
  create_room_lore <room_id> <prompt...>

Examples:
  create_room_lore foyer Mention damp coats by the door
  list_drafts
  approve_draft 2

Notes:
  - Room id must exist in SQLite.
  - For a direct rewrite without the LLM, use add_room_lore.
""",
    "delete_room_lore": """\
delete_room_lore — remove a room lore key from Chroma

Usage:
  delete_room_lore <key>

Examples:
  delete_room_lore room:foyer:description

Notes:
  - May refuse when the key is still required by a room record.
""",
    "list_items": """\
list_items — list item definitions in SQLite

Usage:
  list_items [search=<text>]

Examples:
  list_items
  list_items search=key

Notes:
  - Definitions only; placements and new items are world-builder work.
""",
    "list_item_lore": """\
list_item_lore — list item lore keys in Chroma

Usage:
  list_item_lore [item_id=<id>] [search=<text>]

Examples:
  list_item_lore
  list_item_lore item_id=brass_key

Notes:
  - Read-only listing.
""",
    "view_item_lore": """\
view_item_lore — show full text for one item lore key

Usage:
  view_item_lore <key>

Examples:
  view_item_lore item:brass_key:description

Notes:
  - Key must exist in Chroma.
""",
    "add_item_lore": """\
add_item_lore — write or replace item lore for an existing definition (immediate canon)

Usage:
  add_item_lore <item_id> | <text...>

Examples:
  add_item_lore brass_key | The brass key is cold, with a scratched numeral on the bow.

Notes:
  - Item definition must exist in SQLite. Alias: edit_item_lore.
  - Immediate write (no draft).
""",
    "create_item_lore": """\
create_item_lore — LLM draft for item lore (not canon until approve_draft)

Usage:
  create_item_lore <item_id> <prompt...>

Examples:
  create_item_lore brass_key Emphasize a scratched numeral on the bow
  approve_draft 3

Notes:
  - Item id must exist in SQLite.
""",
    "delete_item_lore": """\
delete_item_lore — remove an item lore key from Chroma

Usage:
  delete_item_lore <key>

Examples:
  delete_item_lore item:brass_key:description

Notes:
  - May refuse when the key is still required by an item definition.
""",
    "list_npcs": """\
list_npcs — list NPC records in SQLite

Usage:
  list_npcs [search=<text>]

Examples:
  list_npcs
  list_npcs search=hale
  list_npcs search=jane

Notes:
  - Shows npc_id, name, room, and lore keys.
""",
    "view_npc": """\
view_npc — show one NPC record and linked Chroma lore

Usage:
  view_npc <npc_id>

Examples:
  view_npc mrs_hale
  view_npc jane

Notes:
  - Read-only; use add_npc or world-builder place_npc to change placement.
""",
    "add_npc_lore": """\
add_npc_lore — write or replace primary NPC lore in Chroma (immediate canon)

Usage:
  add_npc_lore <npc_id> | <text...>

Examples:
  add_npc_lore jane | Jane speaks softly and watches the study door.
  add_npc_lore mrs_hale | Mrs. Hale keeps ink-stained fingers and a steady gaze.

Notes:
  - NPC record must exist. Alias: edit_npc_lore.
  - Immediate write (no draft). For LLM drafts use create_npc_lore or revise_npc_lore.
""",
    "create_npc_lore": """\
create_npc_lore — LLM draft for NPC lore (not canon until approve_draft)

Usage:
  create_npc_lore <npc_id> <prompt...>

Examples:
  create_npc_lore mrs_hale Soften her voice; note ink-stained fingers
  list_drafts
  approve_draft 4

Notes:
  - May rewrite more freely than revise_npc_lore; still grounded on existing lore.
""",
    "revise_npc_lore": """\
revise_npc_lore — LLM draft that folds new detail into existing primary NPC lore

Usage:
  revise_npc_lore <npc_id> <prompt...>

Examples:
  revise_npc_lore mrs_hale She keeps a copper thimble in her pocket
  approve_draft 5

Notes:
  - Keeps established facts unless the prompt explicitly overrides them.
  - Alias: append_npc_lore. Prefer this for incremental NPC building.
""",
    "add_npc": """\
add_npc — create or update an NPC record with existing Chroma lore keys

Usage:
  add_npc <npc_id> | <name> | <lore_key>[,<lore_key>...] [--in <room_id>]

Examples:
  add_npc jane | Jane | npc:jane:description --in study
  add_npc mary | Mary | npc:mary:description

Notes:
  - Every lore key must already exist in Chroma.
  - Does not write lore text; use add_npc_lore or create_npc_lore for that.
  - Omit --in to leave the NPC's current room unchanged.
""",
    "create_npc": """\
create_npc — LLM draft for a new NPC (not live until approve_draft)

Usage:
  create_npc <prompt...>

Examples:
  create_npc A woman named Jane, calm and observant, suited to Quiet Manor
  list_drafts
  view_draft 1
  approve_draft 1

Notes:
  - After approve, place with add_npc ... --in <room> or world-builder place_npc.
""",
    "edit_npc": """\
edit_npc — rename an NPC SQLite record (not lore text)

Usage:
  edit_npc <npc_id> | name=<new name>

Examples:
  edit_npc jane | name=Jane Whitmore

Notes:
  - Does not change lore text; use add_npc_lore for that.
  - Invalidates NPC presentation for players who have seen this NPC.
""",
    "delete_npc": """\
delete_npc — remove an NPC record from SQLite

Usage:
  delete_npc <npc_id>

Examples:
  delete_npc gardener

Notes:
  - Chroma NPC lore keys are left in place; delete lore separately if needed.
""",
    "list_drafts": """\
list_drafts — list pending LLM lore drafts

Usage:
  list_drafts

Examples:
  list_drafts

Notes:
  - Only pending drafts; approved or rejected drafts are not listed.
""",
    "view_draft": """\
view_draft — show one pending draft body and metadata

Usage:
  view_draft <id>

Examples:
  list_drafts
  view_draft 3

Notes:
  - Id comes from list_drafts output.
""",
    "approve_draft": """\
approve_draft — commit a pending draft to canon (Chroma + SQLite refs)

Usage:
  approve_draft <id>

Examples:
  list_drafts
  view_draft 3
  approve_draft 3

Notes:
  - Only pending drafts; invalidates presentation for affected entities.
  - create_* and revise_npc_lore require approve before play sees changes.
""",
    "reject_draft": """\
reject_draft — discard a pending draft without writing canon

Usage:
  reject_draft <id>

Examples:
  list_drafts
  reject_draft 2

Notes:
  - Nothing is written to Chroma or SQLite refs.
""",
    "drafts": """\
drafts — workflow for LLM-assisted canon (topic summary)

Usage:
  create_* / revise_npc_lore / create_npc  →  list_drafts  →  view_draft  →  approve_draft

Examples:
  create_room_lore foyer Mention damp coats by the door
  list_drafts
  view_draft 1
  approve_draft 1

Notes:
  - add_*_lore commands write immediately and skip the draft queue.
  - reject_draft abandons a pending draft.
""",
    "lore": """\
lore — immediate vs draft lore writes (topic summary)

Usage:
  Immediate: add_*_lore <id> | <text...>
  Draft:     create_*_lore ... then approve_draft <id>

Examples:
  add_npc_lore jane | Jane watches the study door.
  create_npc_lore jane Add that she keeps a folded letter
  approve_draft 2

Notes:
  - Aliases edit_*_lore point at add_*_lore (immediate upsert).
  - Bulk structure (rooms, exits, placements) is world-builder, not edit_mode.
""",
}


def resolve_edit_command_help(topic: str) -> str | None:
    """Return per-command help text, or None if the topic is unknown."""
    key = topic.strip().lower().replace("-", "_")
    if not key:
        return None
    canonical = HELP_ALIASES.get(key, key)
    body = EDIT_COMMAND_HELP.get(canonical)
    if body is None:
        return None
    if key != canonical:
        return f"{key} — alias of {canonical}\n\n{body}"
    return body
