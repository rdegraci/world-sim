# World-Sim World Authoring — Build a Small Wing (Step by Step)

Version: 2.1  
Audience: authors who want a guided path to seed a small playable wing  
See also: `docs/README.md` (docs index), `docs/COMMAND-DETAILS.md` (full syntax), `docs/OPERATOR.md` (day-to-day ops), `docs/cache/WORLD_BUILDING.md` (design strategy)

This guide is a **single ordered tutorial**. Complete the use cases in order. Each one depends on the previous. When you finish, you have a small wing with:

| Piece | Id | Where |
|-------|-----|--------|
| Room 1 | `side_parlor` | Attached west of the Quiet Manor `hallway` |
| Room 2 | `reading_room` | North of the side parlor |
| NPC | `miss_ward` | In the side parlor |
| Table | `oak_table` | In the reading room |
| Book | `leather_bound_book` | In the reading room (lore places it on the table) |

Quiet Manor (foyer / hallway / study) is already seeded when you first run the app. You do not rebuild it. You add this wing onto it so you can walk there from play.

**Important:** The runtime places items **in rooms**, not inside other items. There is no “book contained by table” inventory link. You place both the table and the book in `reading_room`, and you write lore so the book rests on the table.

---

## Before you start

1. Install and bootstrap once (`pip install -e .`, run `world-sim` so appdirs and `.env` exist).
2. Set `ADMIN_PASSWORD` in `.env`.
3. Prefer a fixed map while you build:

```yaml
world:
  dynamic_expansion: false
```

4. You will use two CLIs against the **same** appdir:

| Tool | Role in this tutorial |
|------|------------------------|
| `world-builder` | Write Chroma lore, draft structure, validate, apply |
| `world-sim` | Log in as `admin`, playtest, optional text polish in `mode edit` |

Offline Builder/play without a live LLM: `WORLD_SIM_LLM=fake world-builder` and `WORLD_SIM_LLM=fake world-sim`.

---

## Use case 1 — Confirm the live world

**Goal:** See that Quiet Manor exists before you add anything.

**Depends on:** Bootstrap complete.

**Steps:**

1. Start Builder:

```bash
world-builder
```

2. List approved lore and check the live graph:

```text
list_lore room
validate_world --world-only
```

| Command | What it does |
|---------|----------------|
| `list_lore room` | Lists approved room lore in Chroma (you should see foyer, hallway, study keys from the starter seed). |
| `validate_world --world-only` | Checks the live SQLite world against Chroma links. Does not look at a draft plan. |

**Done when:** You see starter room lore and validation does not report a broken starter world. Leave the Builder session open for the next use cases (or restart `world-builder` later; lore persists).

---

## Use case 2 — Write lore for room 1 (side parlor)

**Goal:** Put approved Chroma text for the first new room. No SQLite room yet.

**Depends on:** Use case 1.

**Steps:**

```text
upsert_lore room:side_parlor | The side parlor is a small west room off the hallway. Soft chairs face a cold grate. The air smells faintly of lemon oil. A north doorway leads to a quieter reading room.
list_lore room
```

| Command | What it does |
|---------|----------------|
| `upsert_lore room:side_parlor \| …` | Writes or replaces approved room lore in Chroma under key `room:side_parlor`. Does **not** create a SQLite room. |
| `list_lore room` | Confirms the new key appears with a short preview. |

**Done when:** `list_lore room` shows `room:side_parlor`.

---

## Use case 3 — Write lore for room 2 (reading room)

**Goal:** Approved Chroma text for the second room. Still no SQLite room.

**Depends on:** Use case 2.

**Steps:**

```text
upsert_lore room:reading_room | The reading room is narrow and dim. An oak table stands under a single high window. A leather-bound book rests on the table. The only exit is south, back to the side parlor.
list_lore room
```

| Command | What it does |
|---------|----------------|
| `upsert_lore room:reading_room \| …` | Approves the second room’s canon description in Chroma. Mentions the table and book so room text and item text stay consistent. |

**Done when:** Both `room:side_parlor` and `room:reading_room` appear in `list_lore room`.

---

## Use case 4 — Write lore for the table and the book

**Goal:** Approved item lore for both props that will sit in the reading room.

**Depends on:** Use case 3.

**Steps:**

```text
upsert_lore item:oak_table | A heavy oak table with a scarred top and one shortened leg propped by a folded pamphlet. It stands under the reading-room window.
upsert_lore item:leather_bound_book | A leather-bound book with frayed ribbon. It lies closed on the oak table, title worn smooth.
list_lore item
```

| Command | What it does |
|---------|----------------|
| `upsert_lore item:oak_table \| …` | Approves table definition lore in Chroma. Key `item:oak_table` will become item id `oak_table` when proposed. |
| `upsert_lore item:leather_bound_book \| …` | Approves book lore. States that the book lies on the oak table (presentation only; both will be room placements). |
| `list_lore item` | Confirms both item keys exist. |

**Done when:** `item:oak_table` and `item:leather_bound_book` are listed.

---

## Use case 5 — Write lore for the NPC

**Goal:** Approved NPC lore for Miss Ward, who will greet players in the side parlor.

**Depends on:** Use case 4 (lore-first habit; NPC does not require items, but the wing story is complete).

**Steps:**

```text
upsert_lore npc:miss_ward:description | Miss Ward is neat and soft-spoken, with ink-stained fingers and a grey shawl. She keeps the side parlor tidy and nods toward the reading room when asked about the book.
list_lore npc
```

| Command | What it does |
|---------|----------------|
| `upsert_lore npc:miss_ward:description \| …` | Approves NPC description lore. From this key, Builder will derive NPC id `miss_ward` unless you override it later. |

**Done when:** `npc:miss_ward:description` appears under `list_lore npc`.

---

## Use case 6 — Propose both rooms onto a draft plan

**Goal:** Turn the two room lore keys into **draft** SQLite room ops. Nothing is live yet.

**Depends on:** Use cases 2 and 3 (room lore must exist).

**Steps:**

```text
propose_rooms_from_lore room:side_parlor room:reading_room
preview_seed_plan
```

| Command | What it does |
|---------|----------------|
| `propose_rooms_from_lore room:side_parlor room:reading_room` | Adds create ops for rooms `side_parlor` and `reading_room` to the current draft plan, linked to those lore keys. If a key were missing, Builder would record a gap and fail closed. |
| `preview_seed_plan` | Prints what the draft would change. Confirms create rooms and lore attachments. Still does not write SQLite. |

**Done when:** Preview shows create (or update) for `side_parlor` and `reading_room`, with no missing-lore gaps for those keys.

---

## Use case 7 — Connect the rooms (to each other and to the hallway)

**Goal:** Add exits on the draft so players can reach the wing from Quiet Manor and move between the two rooms.

**Depends on:** Use case 6 (rooms are on the draft). The starter `hallway` room must already exist (it does after seed).

**Steps:**

```text
connect_rooms hallway west side_parlor
connect_rooms side_parlor east hallway
connect_rooms side_parlor north reading_room
connect_rooms reading_room south side_parlor
preview_seed_plan
```

| Command | What it does |
|---------|----------------|
| `connect_rooms hallway west side_parlor` | Draft exit: from hallway, go west into the side parlor. |
| `connect_rooms side_parlor east hallway` | Return exit to the hallway. |
| `connect_rooms side_parlor north reading_room` | Draft exit into room 2. |
| `connect_rooms reading_room south side_parlor` | Return exit to room 1. |
| `preview_seed_plan` | Shows all four exits on the draft. |

**Done when:** Preview lists hallway ↔ side_parlor and side_parlor ↔ reading_room.

---

## Use case 8 — Propose and place the table and book in room 2

**Goal:** Add item definitions and place both instances in `reading_room` on the draft.

**Depends on:** Use cases 4 and 6 (item lore exists; target room is on the draft / will exist on apply).

**Steps:**

```text
propose_items_from_lore item:oak_table item:leather_bound_book --in reading_room
preview_seed_plan
```

| Command | What it does |
|---------|----------------|
| `propose_items_from_lore item:oak_table item:leather_bound_book --in reading_room` | Adds draft ops to create item definitions `oak_table` and `leather_bound_book`, and to place an instance of each in `reading_room`. |

If you proposed definitions earlier without `--in`, place them now:

```text
place_item oak_table --in reading_room
place_item leather_bound_book --in reading_room
```

| Command | What it does |
|---------|----------------|
| `place_item <item_id> --in <room_id>` | Adds a placement op on the draft for an item definition that is already on the plan or will be created with it. |

**Done when:** Preview shows both items defined and placed in `reading_room`.

---

## Use case 9 — Propose and place the NPC in room 1

**Goal:** Add Miss Ward to the draft in the side parlor.

**Depends on:** Use cases 5 and 6.

**Steps:**

```text
propose_npcs_from_lore npc:miss_ward:description --npc_id miss_ward --name "Miss Ward" --in side_parlor
preview_seed_plan
```

| Command | What it does |
|---------|----------------|
| `propose_npcs_from_lore … --npc_id miss_ward --name "Miss Ward" --in side_parlor` | Adds a draft NPC create/update using the approved lore key, forces id and display name, and places her in `side_parlor`. |

If the NPC op exists without a room, set placement:

```text
place_npc miss_ward --in side_parlor
```

**Done when:** Preview shows NPC `miss_ward` in `side_parlor`.

---

## Use case 10 — Validate and apply the plan

**Goal:** Commit the draft to SQLite so the wing becomes live structure.

**Depends on:** Use cases 6–9 (rooms, exits, items, NPC on one draft).

**Steps:**

```text
preview_seed_plan
validate_world
apply_seed_plan
```

At the apply prompt, type exactly:

```text
apply
```

(Or run `apply_seed_plan --yes` to skip the interactive confirm.)

| Command | What it does |
|---------|----------------|
| `preview_seed_plan` | Final human-readable check of rooms, exits, items, NPC. |
| `validate_world` | Checks the draft and live world for missing lore, bad links, and gaps. Do not apply if this fails. |
| `apply_seed_plan` | Writes rooms, exits, item definitions, placements, NPC, and lore-key refs to SQLite. Requires explicit confirmation. |

Optional after apply:

```text
validate_world --world-only
list_plans
```

| Command | What it does |
|---------|----------------|
| `validate_world --world-only` | Re-checks the live world after the commit. |
| `list_plans` | Shows saved plans; the applied plan is retained under `builder/plans/`. |

**Done when:** Apply succeeds and world-only validation is clean. Type `quit` to leave Builder.

---

## Use case 11 — Playtest the wing

**Goal:** Walk the path as a player and confirm rooms, NPC, table, and book.

**Depends on:** Use case 10.

**Steps:**

1. Start play:

```bash
WORLD_SIM_LLM=fake world-sim
```

(Log in as `admin` or any user.)

2. From the foyer, reach the wing and inspect it:

```text
look
go north
go west
look
talk to Miss Ward
end_chat
go north
look
examine oak table
examine leather bound book
take leather bound book
inventory
go south
go east
go south
```

| Command / line | What it does |
|----------------|----------------|
| `look` | Full (or recap) room presentation from canon lore + visible entities. |
| `go north` / `go west` / … | Moves through exits. Path: foyer → hallway → side_parlor → reading_room. |
| `talk to Miss Ward` | Starts Player Chat if she is in your room. |
| `end_chat` | Leaves Player Chat. |
| `examine …` | Full item description from Chroma. |
| `take leather bound book` | Moves the book instance into inventory (table stays in the room). |
| `inventory` | Lists carried items. |

**Done when:** You can enter both rooms, see Miss Ward in the parlor, see the table and book in the reading room, and take the book if you want.

Optional while playtesting dialogue: set `player_chat.lore_guard: true` so NPC replies are judged against must/must_not + her lore (see `docs/OPERATOR.md` §4.2).

---

## Use case 12 — Polish canon text after playtest (optional)

**Goal:** Fix wording without rebuilding structure.

**Depends on:** Use case 10 (entities exist in SQLite). Use case 11 suggested so you know what felt wrong.

**Steps:**

```text
mode edit
list_rooms search=reading
view_room_lore room:reading_room
edit_room_lore reading_room | The reading room is narrow and dim. Dust floats in the window light. An oak table stands beneath it. A leather-bound book rests on the table. The only exit is south, back to the side parlor.
edit_item_lore leather_bound_book | A leather-bound book with a frayed green ribbon. It lies closed on the oak table.
edit_npc_lore miss_ward | Miss Ward is neat and soft-spoken, with ink-stained fingers. She nods toward the north door when guests ask about the book.
mode play
go …   # return to the rooms and look / examine again
```

| Command | What it does |
|---------|----------------|
| `mode edit` | Enters admin-only constrained canon editing. |
| `view_room_lore` | Shows current Chroma text. |
| `edit_room_lore` / `edit_item_lore` / `edit_npc_lore` | Upsert Chroma text for an **existing** room, item definition, or NPC. Same as `add_*_lore`. Invalidates presentation so the next look/examine uses the new full text. Does **not** create rooms. |
| `mode play` | Returns to play to verify. |

**Done when:** The polished text appears on the next full look/examine.

---

## Quick map of the finished wing

```text
foyer --north--> hallway --west--> side_parlor --north--> reading_room
                   |                    |                      |
                 (east)               Miss Ward           oak_table
                 study                                      leather_bound_book
                                                            (on table, via lore)
```

---

## If something fails

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| Propose reports a gap | Lore key not upserted | Re-run the matching use case 2–5 `upsert_lore` |
| Validate fails on exits | Typo in room id | Use `side_parlor` / `reading_room` / `hallway` exactly |
| Apply refused | Gaps or validate errors | Fix lore/links; `preview_seed_plan` again |
| Cannot reach the wing | Exits not applied | Confirm use case 7 was on the same plan you applied |
| `edit_room_lore` says room missing | Applied never ran | Finish use case 10 before polish |
| Expected book “inside” table | Not supported | Both are room items; keep “on the table” in lore |

---

## Related documents

| Doc | Role |
|-----|------|
| `docs/README.md` | Docs index |
| `docs/COMMAND-DETAILS.md` | Full parameter reference for every command |
| `docs/OPERATOR.md` | Play, co-op, config, broader ops |
| `docs/cache/COMMAND-MATRIX.md` | One-page command table |
| `docs/cache/WORLD_BUILDING.md` | Why lore-first seeding |
| `docs/cache/SPEC-WORLD_BUILDER.md` | Builder contract |
| `docs/cache/SPEC-PLAYER-CHAT.md` | Player Chat (optional lore guard for playtest) |
| `examples/seed-brief-cellar.yaml` | Separate sample brief (cellar wing), not required for this tutorial |
