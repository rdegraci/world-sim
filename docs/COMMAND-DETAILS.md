# World-Sim Command Details

Version: 1.1  
Audience: operators who need full syntax and behavior for each command  
See also: `docs/README.md` (docs index), `docs/OPERATOR.md` (use cases and overview), `docs/cache/COMMAND-MATRIX.md` (cheat sheet)

This document expands **section 5** of `OPERATOR.md`. Each command has its own section: what it does, parameters, and notes.

Command tokens are literal text. Angle brackets mark required values. Square brackets mark optional values. A pipe `|` separates fields on one line where the CLI requires it.

---

## 1. world-sim (any mode)

These work in the `world-sim` CLI session shell regardless of play/edit/chat mode (except where noted).

### 1.1 `help`

**What it does:** Prints help for the current mode.

**Parameters:** none.

**Notes:**

- In `edit_mode`, prints the edit command list.
- In `chat_mode`, prints chat help.
- In `play_mode`, prints the general session help.

**Example:**

```text
help
```

### 1.2 `mode play`

**What it does:** Switches the session to `play_mode` (or confirms you are already there).

**Parameters:** none (the word `play` is required after `mode`).

**Example:**

```text
mode play
```

### 1.3 `mode edit`

**What it does:** Switches to admin-only `edit_mode` for constrained canon commands.

**Parameters:** none (the word `edit` is required after `mode`).

**Notes:**

- Non-admin users are refused.
- Leaves Player Chat if you were talking (you should `end_chat` first when possible).

**Example:**

```text
mode edit
```

### 1.4 `mode chat`

**What it does:** Switches to admin-only sandboxed `chat_mode` with the configured chat NPC.

**Parameters:** none (the word `chat` is required after `mode`).

**Notes:**

- Non-admin users are refused.
- Does not mutate world state or canon lore.
- Chat NPC comes from `chat_npc_id` in `config.yaml` (default `mrs_hale`).

**Example:**

```text
mode chat
```

### 1.5 `whoami`

**What it does:** Prints the authenticated username, role, player character id/name, and session id.

**Parameters:** none.

**Example:**

```text
whoami
```

### 1.6 `quit`

**What it does:** Ends the CLI session and exits the process.

**Parameters:** none.

**Aliases:** `exit`, `q`.

**Example:**

```text
quit
```

---

## 2. world-sim · play

Unless noted, lines that are not shell commands go to `PlayOrchestrator.handle_action`. Clear `go …` / direction lines bypass the LLM and call movement tools directly. Other phrases may use the LLM with play tools (`move_player`, `take_item`, `look_room`, `examine_item`, `examine_npc`, `advance_time`, and optional memory tools).

### 2.1 `look`

**What it does:** Presents the full canonical room description for the current room (and updates full-description-seen for this player character when appropriate).

**Parameters:** none for the common shorthand. Free-text lines may also ask the model to call `look_room`.

**Stores:** Reads SQLite room placement and Chroma room lore. May update SQLite presentation state.

**Example:**

```text
look
```

### 2.2 `go <direction>`

**What it does:** Moves the player through an exit in the given direction. If the exit is a pending frontier stub and `world.dynamic_expansion` is true, realizes the stub under `WorldAuthority`, then moves.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `direction` | yes | Exit key or alias: `north`/`n`, `south`/`s`, `east`/`e`, `west`/`w`, `up`/`u`, `down`/`d` |

**Also accepted:** `go west`, `walk west`, `move west`, or a bare direction such as `west` / `n` (direct move parser).

**Notes:**

- Contested exits use claim locks. A crowded exit returns a runtime refusal.
- With expansion off, stubs are sealed and do not create rooms.
- Realization writes SQLite structure and emits `room_realized`.

**Example:**

```text
go north
go west
```

### 2.3 `take …`

**What it does:** Picks up an item instance from the current room into the player inventory.

**Parameters (via tool / natural language):**

| Name | Required | Meaning |
|------|----------|---------|
| item name fragment | usually | Matched against visible room items (case-insensitive substring) |
| `item_instance_id` | optional | Exact instance id when the model or caller supplies it |

**Notes:**

- Contested takes: one success, others get structured refusal (`item_gone` / `item_claimed`).
- Emits scene-public `item_taken` for the room.

**Example:**

```text
take brass key
```

### 2.4 `examine …`

**What it does:** Presents the full canonical description for a visible item instance or a present NPC.

**Parameters:**

| Target | Meaning |
|--------|---------|
| Item | Name fragment or instance id in the room (or inventory, depending on tool resolution) |
| NPC | Name or `npc_id` for an NPC in the current room |

**Stores:** Reads Chroma lore. Updates per-player presentation seen-state in SQLite.

**Example:**

```text
examine brass key
examine mrs hale
```

### 2.5 `wait <minutes>`

**What it does:** Advances the shared world clock by the given number of minutes.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `minutes` | yes | Non-negative integer (via `advance_time` tool) |

**Example:**

```text
wait 10
```

### 2.6 `inventory`

**What it does:** Lists items the player character currently carries (CLI special-case; does not require the LLM).

**Parameters:** none.

**Notes:** Refused while you are inside focused Player Chat. Type `end_chat` first.

**Example:**

```text
inventory
```

### 2.7 `talk to <npc>` / `speak to <npc>`

**What it does:** Starts focused Player Chat with a present NPC. Acquires an exclusive chat lease on that NPC.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| NPC query | yes | Name fragment or id matched against NPCs in the current room |

**Accepted openers:** `talk to …`, `talk …`, `speak to …`, `speak with …`, `chat with …`.

**Notes:**

- NPC must share your room.
- Under co-op, a second player gets a busy/leased refusal and never sees private chat text.
- Prompt becomes `talk>` until chat ends.
- Optional `player_chat.lore_guard` (default off) judges each NPC reply against config `must` / `must_not` plus that NPC's lore; failed replies regenerate then refuse in character.

**Example:**

```text
talk to Mrs. Hale
speak to mrs_hale
```

### 2.8 `end_chat`

**What it does:** Ends focused Player Chat and returns to normal play. Releases the NPC chat lease.

**Parameters:** none on the CLI line. The LLM may also call tool `end_player_chat` with optional `reason`.

**Example:**

```text
end_chat
```

### 2.9 Optional play tools (when enabled)

These appear in the LLM tool list only when config enables them. They are not separate shell keywords.

#### `record_memory` (`memory.enabled: true`)

| Parameter | Required | Meaning |
|-----------|----------|---------|
| `summary` | yes | Short memory text (length capped by `memory.max_summary_chars`) |
| `about_kind` | no | `player_character`, `npc`, `room`, `item`, or `world` |
| `about_id` | no | Id matching `about_kind` |
| `lore_key` | no | Optional link only (does not edit Chroma) |

Writes a bounded SQLite memory for the acting player character (or NPC-about-player under rules). Private. No scene-public event.

#### `forget_memory` (`memory.enabled: true`)

| Parameter | Required | Meaning |
|-----------|----------|---------|
| `memory_id` | yes | Integer id of a memory you own |

---

## 3. world-sim · edit (admin)

Enter with `mode edit`. All commands below are admin-only.

### 3.1 Lore browse (Chroma)

#### 3.1.1 `list_system_lore`

**What it does:** Lists system lore keys with a short text preview.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `search=…` | no | Substring filter on key or text (case-insensitive) |

**Example:**

```text
list_system_lore
list_system_lore search=manor
```

#### 3.1.2 `view_system_lore`

**What it does:** Prints the full Chroma text for one system lore key.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `key` | yes | Stable lore key |

**Example:**

```text
view_system_lore system:quiet_manor:overview
```

#### 3.1.3 `list_room_lore`

**What it does:** Lists room lore keys with short previews.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `room_id=…` | no | Limit to lore linked to this SQLite room |
| `search=…` | no | Substring filter on key or text |

**Example:**

```text
list_room_lore
list_room_lore room_id=foyer
list_room_lore search=coat
```

#### 3.1.4 `view_room_lore`

**What it does:** Prints full room lore text for a key.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `key` | yes | Room lore key (often `room:<id>:…`) |

**Example:**

```text
view_room_lore room:foyer:description
```

#### 3.1.5 `list_item_lore`

**What it does:** Lists item definition lore keys with short previews.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `item_id=…` | no | Limit to lore for this item definition id |
| `search=…` | no | Substring filter |

**Example:**

```text
list_item_lore item_id=brass_key
```

#### 3.1.6 `view_item_lore`

**What it does:** Prints full item lore text for a key.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `key` | yes | Item lore key |

**Example:**

```text
view_item_lore item:brass_key:description
```

### 3.2 Structure / records (SQLite)

#### 3.2.1 `list_rooms`

**What it does:** Lists rooms in the SQLite world graph (`room_id`, name, lore_key).

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `search=…` | no | Filter on room id or name |

**Example:**

```text
list_rooms
list_rooms search=hall
```

#### 3.2.2 `list_items`

**What it does:** Lists item definitions (`item_id`, name, lore_key).

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `search=…` | no | Filter on id or name |

**Example:**

```text
list_items search=key
```

#### 3.2.3 `list_npcs`

**What it does:** Lists NPC records (`npc_id`, name, room, lore keys).

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `search=…` | no | Filter on id or name |

**Example:**

```text
list_npcs
list_npcs search=hale
```

#### 3.2.4 `view_npc`

**What it does:** Shows one NPC record and loads linked Chroma lore for reading.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | NPC identifier |

**Example:**

```text
view_npc mrs_hale
```

#### 3.2.5 `add_npc`

**What it does:** Creates or updates an NPC SQLite record and attaches existing Chroma lore keys. Does not invent missing lore text.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | New or existing NPC id |
| `name` | yes | Display name |
| `lore_keys` | yes | One or more keys, comma-separated |
| `--in <room>` | no | Place NPC in this room id |

Fields are separated by `|`.

**Notes:** Each lore key must already exist in Chroma. Fails closed if a key is missing. Invalidates NPC presentation.

**Example:**

```text
add_npc gardener | Gardener | npc:gardener:description --in foyer
```

#### 3.2.6 `edit_npc`

**What it does:** Renames an NPC record. Invalidates presentation for that NPC.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | Existing NPC |
| `name=<new name>` | yes | New display name after `|` |

**Example:**

```text
edit_npc gardener | name=Head Gardener
```

#### 3.2.7 `delete_npc`

**What it does:** Deletes the NPC SQLite record. Chroma lore keys remain (may become unused).

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | NPC to remove |

**Example:**

```text
delete_npc gardener
```

### 3.3 Canon writes that bridge both

#### 3.3.1 `add_system_lore` / `edit_system_lore`

**What it does:** Writes system lore text to Chroma and records a lore-key ref in SQLite. Replaces existing text for the same key (upsert).

**Alias:** `edit_system_lore` is identical to `add_system_lore`. `add_system_lore` is the canonical spelling.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `key` | yes | Lore key before `|` |
| `text` | yes | Full lore body after `|` |

**Example:**

```text
add_system_lore system:quiet_manor:bell | The manor bell marks evening in the Quiet Manor.
edit_system_lore system:quiet_manor:bell | The manor bell marks evening in the Quiet Manor.
```

#### 3.3.2 `create_system_lore`

**What it does:** Asks the LLM for a reviewable system lore draft. Stores a **pending** draft in SQLite only.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `prompt` | yes | Free-text instruction after the command name |

**Example:**

```text
create_system_lore A note about the manor evening bell
```

#### 3.3.3 `delete_system_lore`

**What it does:** Deletes a system lore key from Chroma when allowed.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `key` | yes | System lore key |

**Example:**

```text
delete_system_lore system:quiet_manor:bell
```

#### 3.3.4 `add_room_lore` / `edit_room_lore`

**What it does:** Replaces Chroma lore for an **existing** room’s lore key. Upserts lore-key ref. Invalidates room presentation for all players.

**Alias:** `edit_room_lore` is identical to `add_room_lore`. `add_room_lore` is the canonical spelling.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `room_id` | yes | Existing SQLite room before `|` |
| `text` | yes | New full lore after `|` |

**Does not create rooms.** Use `world-builder` for new rooms.

**Example:**

```text
add_room_lore foyer | The foyer is quiet, with damp coats by the door.
edit_room_lore foyer | The foyer is quiet, with damp coats by the door.
```

#### 3.3.5 `create_room_lore`

**What it does:** Creates a pending LLM draft for an existing room’s lore.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `room_id` | yes | Existing room |
| `prompt` | yes | Remainder of the line (draft instruction) |

**Example:**

```text
create_room_lore foyer Mention damp coats by the door
```

#### 3.3.6 `delete_room_lore`

**What it does:** Deletes a room lore key from Chroma only if no SQLite room still links it.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `key` | yes | Room lore key |

**Example:**

```text
delete_room_lore room:cellar:description
```

#### 3.3.7 `add_item_lore` / `edit_item_lore`

**What it does:** Replaces Chroma lore for an existing item definition. Invalidates presentation for related instances.

**Alias:** `edit_item_lore` is identical to `add_item_lore`. `add_item_lore` is the canonical spelling.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `item_id` | yes | Item definition id before `|` |
| `text` | yes | New lore after `|` |

**Example:**

```text
add_item_lore brass_key | A small brass key with a scratched numeral on the bow.
edit_item_lore brass_key | A small brass key with a scratched numeral on the bow.
```

#### 3.3.8 `create_item_lore`

**What it does:** Pending LLM draft for an existing item definition.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `item_id` | yes | Existing definition |
| `prompt` | yes | Draft instruction |

**Example:**

```text
create_item_lore brass_key Emphasize a scratched numeral
```

#### 3.3.9 `delete_item_lore`

**What it does:** Deletes item lore from Chroma only if no definition still links the key.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `key` | yes | Item lore key |

#### 3.3.10 `add_npc_lore` / `edit_npc_lore`

**What it does:** Writes primary NPC lore text to Chroma, updates the NPC record’s lore key list, invalidates presentation.

**Alias:** `edit_npc_lore` is identical to `add_npc_lore`. `add_npc_lore` is the canonical spelling. This is **not** `edit_npc` (rename only).

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | Existing NPC before `|` |
| `text` | yes | New description after `|` |

**Example:**

```text
add_npc_lore mrs_hale | Mrs. Hale is tidy and watchful, with silver hair and a charcoal cardigan.
edit_npc_lore mrs_hale | Mrs. Hale is tidy and watchful, with silver hair and a charcoal cardigan.
```

#### 3.3.11 `create_npc_lore`

**What it does:** Pending LLM draft that replaces the **primary** lore text for an existing NPC. Grounded on system lore and that NPC’s linked lore. Freer rewrite than `revise_npc_lore`. Not live until `approve_draft`. Does not create NPCs.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | Existing NPC |
| `prompt` | yes | Draft instruction |

**Example:**

```text
create_npc_lore mrs_hale Soften her voice; note ink-stained fingers
```

**Notes:** Keeps the NPC’s id, display name, room, and condition. Only the primary description text is rewritten on approve (same key `add_npc_lore` updates).

#### 3.3.12 `revise_npc_lore` / `append_npc_lore`

**What it does:** Pending LLM draft that **keeps** the existing primary NPC description and folds in the admin prompt as new detail. Grounded on system lore and that NPC’s linked lore. Not live until `approve_draft`. Does not create NPCs or add a second lore key.

**Alias:** `append_npc_lore` is identical to `revise_npc_lore`. `revise_npc_lore` is the canonical spelling.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | Existing NPC |
| `prompt` | yes | Detail to incorporate |

**Example:**

```text
revise_npc_lore mrs_hale She keeps a copper thimble in her pocket
append_npc_lore mrs_hale She dislikes the cellar door left ajar
```

**Notes:** Still stores one full primary description (merge/revise, not a Chroma append). Prefer this when building an NPC slowly; use `create_npc_lore` when a freer rewrite is fine.

#### 3.3.13 `create_npc`

**What it does:** Pending LLM draft for a new NPC (lore + record fields). Not live until `approve_draft`.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `prompt` | yes | Free-text creation instruction |

**Example:**

```text
create_npc A gardener who tends the courtyard pots
```

#### 3.3.14 `list_drafts`

**What it does:** Lists **pending** lore drafts in SQLite (`id`, collection, key, status).

**Parameters:** none.

**Notes:** Only pending drafts appear. Approved or rejected drafts are not listed here.

#### 3.3.15 `view_draft`

**What it does:** Shows one draft’s full body and metadata.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `id` | yes | Integer draft id |

**Example:**

```text
view_draft 1
```

#### 3.3.16 `approve_draft`

**What it does:** Commits a pending draft to Chroma. May create/update NPC rows and lore-key refs. Invalidates presentation for affected entities.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `id` | yes | Integer draft id |

**Example:**

```text
approve_draft 1
```

#### 3.3.17 `reject_draft`

**What it does:** Marks a draft rejected. Does not write canon lore.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `id` | yes | Integer draft id |

**Example:**

```text
reject_draft 2
```

---

## 4. world-builder

Run `world-builder`. Shares the same appdir as `world-sim`. Plans save under `<data_dir>/builder/plans/`.

### 4.1 `help`

**What it does:** Prints Builder command help.

**Parameters:** none.

### 4.2 `list_lore`

**What it does:** Lists approved Chroma lore as `collection`, `key`, short preview.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| collection | no | `system`, `room`, `item`, `npc`, or full collection name. Omit to list all. |

**Example:**

```text
list_lore
list_lore room
```

### 4.3 `upsert_lore`

**What it does:** Writes or replaces approved lore text in Chroma. Does **not** create SQLite rooms, items, or NPCs.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `lore_key` | yes | Key before `|` (or `collection lore_key` before `|`) |
| `text` | yes | Body after `|` |
| collection | no | Explicit `system` / `room` / `item` / `npc` when key prefix is ambiguous |

**Example:**

```text
upsert_lore room:cellar | The cellar is a cool stone room under the hallway.
upsert_lore room room:cellar | The cellar is a cool stone room under the hallway.
```

### 4.4 `discover_lore`

**What it does:** Semantic retrieval assist over Chroma. Re-grounds hits with `get_lore`. Requires `retrieval.enabled: true`.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `query` | yes | Free-text search terms (remainder of the line) |

**Example:**

```text
discover_lore damp cellar bottles
```

### 4.5 `propose_discovered`

**What it does:** Runs retrieval, then proposes only **grounded** keys into the current draft plan. Fail closed if none. Requires retrieval enabled.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `kind` | yes | `rooms`, `items`, or `npcs` |
| `query` | yes | Free-text after kind |
| `--in <room_id>` | no | Placement room for items/NPCs |

**Example:**

```text
propose_discovered rooms cellar under manor
propose_discovered items lantern --in cellar
```

### 4.6 `propose_rooms_from_lore`

**What it does:** Adds room create/update ops to the draft plan from approved room lore keys. Missing lore becomes a gap (fail closed).

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `lore_key`… | yes | One or more room lore keys |

**Example:**

```text
propose_rooms_from_lore room:cellar
```

### 4.7 `propose_items_from_lore`

**What it does:** Adds item definition ops to the draft from item lore keys.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `lore_key`… | yes | One or more item lore keys |
| `--in <room_id>` | no | Also place an instance in this room on the draft |

**Example:**

```text
propose_items_from_lore item:oil_lantern --in cellar
```

### 4.8 `propose_npcs_from_lore`

**What it does:** Adds NPC create/update ops from NPC lore keys.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `lore_key`… | yes | One or more NPC lore keys |
| `--npc_id <id>` | no | Force NPC id |
| `--name <name>` | no | Force display name |
| `--in <room>` | no | Place NPC in room on the draft |

**Example:**

```text
propose_npcs_from_lore npc:mrs_hale:description --in study
```

### 4.9 `propose_from_brief`

**What it does:** Loads a guidance brief file and builds a **draft** seed plan from current approved lore. Does not apply. Brief is intent only, not canon.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `path` | yes | Path to YAML/Markdown brief |

**Example:**

```text
propose_from_brief examples/seed-brief-cellar.yaml
```

### 4.10 `connect_rooms`

**What it does:** Adds a directed exit to the draft plan.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `from` | yes | From room id |
| `direction` | yes | Exit direction |
| `to` | yes | To room id |

**Example:**

```text
connect_rooms hallway down cellar
```

### 4.11 `place_item`

**What it does:** Adds an item placement op to the draft.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `item_id` | yes | Item definition id |
| `--in <room_id>` | yes | Target room |

**Example:**

```text
place_item oil_lantern --in cellar
```

### 4.12 `place_npc`

**What it does:** Adds an NPC placement op to the draft.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | NPC id |
| `--in <room_id>` | yes | Target room |

**Example:**

```text
place_npc mrs_hale --in study
```

### 4.13 `attach_room_lore`

**What it does:** Attaches a lore key to a room on the draft plan.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `room_id` | yes | Room id |
| `lore_key` | yes | Room lore key |

### 4.14 `attach_item_lore`

**What it does:** Attaches a lore key to an item definition on the draft.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `item_id` | yes | Definition id |
| `lore_key` | yes | Item lore key |

### 4.15 `attach_npc_lore`

**What it does:** Attaches a lore key to an NPC on the draft.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `npc_id` | yes | NPC id |
| `lore_key` | yes | NPC lore key |

### 4.16 `preview_seed_plan`

**What it does:** Prints a human-readable preview of the draft (or a named plan).

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `plan_id` | no | Defaults to the current plan |

**Example:**

```text
preview_seed_plan
preview_seed_plan plan_20260730T120000Z_abc123
```

### 4.17 `validate_world`

**What it does:** Validates the live world and optionally the draft plan (missing lore, bad links, brief caps, hierarchy).

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `--plan <plan_id>` | no | Validate this plan (else current if present) |
| `--world-only` | no | Skip plan checks. Validate live SQLite/Chroma only |

**Example:**

```text
validate_world
validate_world --world-only
validate_world --plan plan_20260730T120000Z_abc123
```

### 4.18 `apply_seed_plan`

**What it does:** Commits a draft plan to SQLite (and required lore links). Explicit confirmation required unless `--yes`.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `plan_id` | no | Defaults to current plan |
| `--yes` / `-y` | no | Skip interactive `apply` confirmation |

**Notes:** Without `--yes`, prints preview and asks you to type exactly `apply`. Ungated auto-apply is not enabled (Exp-007).

**Example:**

```text
apply_seed_plan
apply_seed_plan --yes
```

### 4.19 `add_frontier_stub`

**What it does:** Registers a pending unrealized exit bound to approved lore. Does not create the target room yet.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `from` | yes | Existing from-room id |
| `direction` | yes | Exit direction from that room |
| `--to <room_id>` | yes | Future/target room id |
| `--lore <lore_key>` | yes | Approved room lore key (must exist) |
| `--name <Name>` | no | Display name for the target |
| `--return <dir>` | no | Return direction from target |

**Example:**

```text
add_frontier_stub hallway west --to garden --lore room:garden --name "Kitchen Garden" --return east
```

### 4.20 `list_frontier_stubs`

**What it does:** Lists frontier stubs and status.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| status filter | no | `pending` or `realized`. Omit for all. |

**Example:**

```text
list_frontier_stubs
list_frontier_stubs pending
```

### 4.21 `list_plans`

**What it does:** Lists saved plan ids. Marks the current plan with `*`.

**Parameters:** none.

### 4.22 `open_plan`

**What it does:** Loads a saved plan as the current draft/applied plan context.

**Parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `plan_id` | yes | Plan identifier |

**Example:**

```text
open_plan plan_20260730T120000Z_abc123
```

### 4.23 `quit` / `exit`

**What it does:** Leaves the Builder REPL.

**Parameters:** none.

---

## 5. world-sim-serve

Start with:

```bash
world-sim-serve --host 127.0.0.1 --port 8765
```

| CLI flag | Default | Meaning |
|----------|---------|---------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8765` | HTTP/WS port |

Same appdir world as `world-sim`. Use TLS termination for `wss://` in real deploys.

### 5.1 `GET /`

**What it does:** Serves the thin web client (play text, say, presence, map).

**Parameters:** none.

### 5.2 `GET /health`

**What it does:** Health check. Returns `{"status":"ok"}`.

**Parameters:** none.

### 5.3 `POST /api/login`

**What it does:** Authenticates a user (and may sign up a new player). Returns a session token for WebSocket and HTTP APIs.

**JSON body:**

| Field | Required | Meaning |
|-------|----------|---------|
| `username` | yes | Login name |
| `password` | yes | Password |
| `allow_signup` | no | Default true. Create player user if missing |

**Notes:** Username `admin` uses `ADMIN_PASSWORD` from `.env`.

### 5.4 `GET /api/me`

**What it does:** Returns the authenticated user and player character for the bearer token.

**Headers:** `Authorization: Bearer <token>`.

### 5.5 `GET /api/presence`

**What it does:** Returns in-room presence for the caller’s current room (roster and busy NPCs).

**Auth:** required.

### 5.6 `GET /api/map`

**What it does:** Returns a fogged schematic map payload for the caller’s player character.

**Query parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `lod` | no | `near` (default), `far`, or `overview` |

**Auth:** required.

### 5.7 `POST /api/say`

**What it does:** Emits scene-public speech in the current room.

**JSON body:**

| Field | Required | Meaning |
|-------|----------|---------|
| `text` | yes | Spoken line (HTTP body max length 500) |

**Auth:** required.

### 5.8 `POST /api/action`

**What it does:** Runs one play line (same path as CLI play actions).

**JSON body:**

| Field | Required | Meaning |
|-------|----------|---------|
| `text` | yes | Play command or natural language action (HTTP body max length 2000) |

**Auth:** required.

### 5.9 `POST /api/move`

**What it does:** Moves in a direction (equivalent to `go <direction>`).

**JSON body:**

| Field | Required | Meaning |
|-------|----------|---------|
| `direction` | yes | Direction or alias |

**Auth:** required.

### 5.10 `WS /ws?token=…`

**What it does:** Persistent play connection. Sends `hello` with opening text, presence, and map. Fans out scene-public room events. Accepts JSON client messages.

**Query parameters:**

| Name | Required | Meaning |
|------|----------|---------|
| `token` | yes | Token from `POST /api/login` |

**Client → server message `type` values:**

| `type` | Fields | Meaning |
|--------|--------|---------|
| `ping` | — | Server replies `pong` |
| `say` | `text` | Public say in current room |
| `action` | `text` | Play line |
| `move` | `direction` | Move |
| `get_map` | `lod` optional | Request map refresh |
| `get_presence` | — | Request presence refresh |

**Server → client (common):** `hello`, `reply`, `presence`, `map`, `event` (scene-public), `error`, `pong`.

**Example client messages:**

```json
{"type": "action", "text": "look"}
{"type": "say", "text": "Hello"}
{"type": "move", "direction": "north"}
{"type": "get_map", "lod": "near"}
{"type": "get_presence"}
```

### 5.11 Map panel (thin web UI)

**What it does:** Renders the server map as an SVG graph. Not a second authority.

**Behavior:**

- Nodes = rooms. Edges = exits.
- You-are-here marker on the current room.
- Other players as dots on revealed rooms only.
- Fog omits unseen rooms.
- LOD control: Near vs Overview.
- Click an adjacent revealed room to send a move intent. The server validates.

---

## Related documents

| Doc | Role |
|-----|------|
| `docs/README.md` | Docs index |
| `docs/OPERATOR.md` | Use cases and short command tables |
| `docs/WORLD-AUTHORING.md` | Step-by-step world-authoring tutorial |
| `docs/cache/COMMAND-MATRIX.md` | One-page cheat sheet |
| `README.md` | Install and status |
| `docs/cache/BUSINESS-RULES.md` | Canon vs runtime rules |
| `docs/cache/SPEC-PLAYER-CHAT.md` | Player Chat + optional lore guard |
