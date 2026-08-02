# World-Sim Operator Manual

Version: 1.2  
Audience: operators who run play sessions, maintain canon, seed structure, or host small co-op  
See also: `docs/README.md` (docs index), `docs/WORLD-AUTHORING.md` (world-authoring tutorial), `docs/COMMAND-DETAILS.md` (full per-command detail), `docs/cache/COMMAND-MATRIX.md` (cheat sheet), `README.md` (install and status), `docs/cache/README.md` (design docs)

This manual covers day-to-day use of the three entry points and the main work flows. It does not replace design specs under `docs/cache/`.

## 1. What you run

| Command | Role |
|---------|------|
| `world-sim` | Local CLI: play, admin edit, admin sandbox chat |
| `world-builder` | Structure seed: lore → draft plan → preview → validate → apply |
| `world-sim-serve` | Multi-session HTTP + WebSocket host (thin web + map) |

All three share one appdir: the same `config.yaml`, `.env`, SQLite world, and Chroma lore store.

Contested play mutations (take, move, frontier realize, Player Chat lease) go through `WorldAuthority`. The LLM narrates after the runtime result. It does not decide winners.

## 2. First-time setup

1. Install the package: `pip install -e .`
2. Run `world-sim` once so bootstrap can create app directories and a `.env` template.
3. Edit `.env` in the config directory.
4. Set `GROK_API_KEY` (required for provider `grok`) or use `WORLD_SIM_LLM=fake` for offline play.
5. Set `ADMIN_PASSWORD` if you will log in as `admin`.
6. Run `world-sim` again, or start `world-sim-serve`.

Paths use `platformdirs` for the `world-sim` app:

- Config directory: `.env`, `config.yaml`
- Data directory: `world_sim.sqlite3`, `chroma/`, Builder plans under `builder/plans/`

On some platforms config and data share one root. Runtime files then live under a `data/` subdirectory.

Offline play (no live LLM calls):

```bash
WORLD_SIM_LLM=fake world-sim
```

## 3. Modes and roles

| Mode | Who | Purpose |
|------|-----|---------|
| `play_mode` | Any player | Room play, tools, Player Chat with a present NPC |
| `edit_mode` | Admin only | Constrained canon maintenance (lore / NPCs) |
| `chat_mode` | Admin only | Sandboxed talk with one configured NPC (no world writes) |

Player Chat (`talk to <npc>`) is inside play. It is not admin `mode chat`.

Login:

- New users sign up with a username and password (stored as hashes in SQLite).
- Username `admin` uses `ADMIN_PASSWORD` from `.env`.

## 4. Use cases

### 4.1 Play the Quiet Manor (single player)

1. Start: `WORLD_SIM_LLM=fake world-sim` (or real provider after keys are set).
2. Log in as a normal user or as `admin`.
3. You start in the foyer.

Useful play lines:

```text
look
go north
take brass key
examine brass key
go east
wait 10
inventory
help
whoami
quit
```

Type `help` in any mode for the local command list.

### 4.2 Talk to an NPC in play (Player Chat)

The NPC must be in your current room.

1. Move to the study: `go north`, then `go east`.
2. Start chat: `talk to Mrs. Hale` (or `speak to Mrs. Hale`).
3. Speak on the `talk>` prompt.
4. End: `end_chat`.
5. Continue normal play: `look`.

Rules:

- Conversation only. No inventory handoff inside this loop.
- Under co-op, one Player Chat lease per NPC. A second player sees the NPC as busy and cannot read private chat text.
- Optional lore guard (default off). Enable in `config.yaml`:

```yaml
player_chat:
  lore_guard: true
  max_regenerations: 1
  # optional: override built-in policy lines
  # must: [...]
  # must_not: [...]
```

When on, each NPC reply is judged against global must/must_not plus that NPC’s lore. On fail: regenerate, then refuse in character. Lore is not rewritten.

### 4.3 Admin sandbox chat (non-canon)

1. Log in as `admin`.
2. Enter: `mode chat`.
3. Talk to the configured chat NPC (default Mrs. Hale from `chat_npc_id`).
4. Return: `mode play`.

This mode must not change inventories, placements, or canon lore.

### 4.4 Edit canon in the runtime (admin)

Use `edit_mode` for small lore or NPC fixes. Use `world-builder` for new rooms, exits, and bulk placements.

1. Log in as `admin`.
2. Enter: `mode edit`.
3. Browse, then draft or write, then approve if the path uses a draft.

LLM draft path (must approve before canon):

```text
mode edit
create_room_lore foyer Mention damp coats by the door
list_drafts
view_draft 1
approve_draft 1
mode play
look
```

After `approve_draft`, the next full encounter or look uses the new full description. Seen-state and stable recap for that entity are cleared.

Direct write (no LLM) for an existing room:

```text
add_room_lore foyer | Direct rewrite without LLM
```

Other useful edit commands:

```text
list_rooms
list_room_lore search=foyer
view_room_lore room:foyer:description
create_item_lore brass_key Emphasize a scratched numeral
create_npc_lore mrs_hale Soften her voice; note ink-stained fingers
revise_npc_lore mrs_hale She keeps a copper thimble in her pocket
append_npc_lore mrs_hale She dislikes the cellar door left ajar
create_npc A gardener who tends the courtyard pots
approve_draft 2
add_npc gardener | Gardener | npc:gardener:description --in foyer
list_npcs
view_npc mrs_hale
create_system_lore A note about the manor evening bell
approve_draft 3
delete_room_lore <key>
reject_draft <id>
```

Notes:

- `add_room_lore` does not create a room. It only changes lore for an existing `room_id`.
- `create_*` commands stay drafts until `approve_draft`.
- Delete of lore fails if a live room or item definition still links that key (guards apply).

### 4.5 Seed new structure with World Builder

Builder writes structure to SQLite only after an explicit apply. Lore in Chroma comes first.

1. Seed Quiet Manor once (`world-sim` or `world-builder`).
2. Start Builder: `world-builder`.
3. Write approved lore (no rooms yet):

```text
upsert_lore room:cellar | The cellar is a cool stone room under the hallway, with packed earth corners and a single oil-stained shelf.
upsert_lore item:oil_lantern | An oil lantern with a soot-dark chimney and a brass handle worn smooth.
list_lore room
```

4. Propose from a guidance brief (intent only, not canon):

```text
propose_from_brief examples/seed-brief-cellar.yaml
preview_seed_plan
validate_world
apply_seed_plan
```

5. At the apply prompt, type `apply` (or use `--yes` where the CLI allows it).
6. Play in `world-sim` and walk into the new structure.

If the brief names lore keys that are missing in Chroma, Builder fails closed. Gaps appear on the plan. Validate and apply refuse. Approved lore wins over brief intent.

Propose from explicit keys instead of a brief:

```text
propose_rooms_from_lore room:cellar
propose_items_from_lore item:oil_lantern --in cellar
connect_rooms hallway down cellar
place_item oil_lantern --in cellar
preview_seed_plan
validate_world
apply_seed_plan
```

Plan management:

```text
list_plans
open_plan <plan_id>
```

Ungated LLM auto-apply is not enabled (Exp-007).

### 4.6 Optional semantic discovery (retrieval assist)

Default: off. Set in `config.yaml`:

```yaml
retrieval:
  enabled: true
  top_k: 5
  builder_discover: true
  play_context: true
```

In `world-builder`:

```text
discover_lore damp cellar bottles
propose_discovered rooms cellar under manor
```

Rules:

- Hits are re-checked with `get_lore`. Ungrounded keys are dropped.
- Suggestions are not world truth. Authoritative facts stay SQLite + explicit lore keys.
- Play context may show an assist block when enabled. Treat it as suggestion only.

### 4.7 Optional bounded memory

Default: off. Set in `config.yaml`:

```yaml
memory:
  enabled: true
  max_per_subject: 20
  max_summary_chars: 280
  ttl_days: 0
```

When on, play may use `record_memory` / `forget_memory` tools (via the LLM tool loop). Memory is runtime SQLite state with caps. It does not rewrite Chroma canon. One character cannot read another character's private memory.

### 4.8 Prepare a frontier stub, then grow the map

Default expansion is off. Campaign identity: realized rooms stay when you later turn expansion off.

1. Keep `world.dynamic_expansion: false` while you build and playtest.
2. Approve lore, then add a stub in `world-builder`:

```text
upsert_lore room:garden | A walled kitchen garden of damp earth and clipped rosemary.
add_frontier_stub hallway west --to garden --lore room:garden --name "Kitchen Garden" --return east
list_frontier_stubs pending
```

3. With expansion off, play cannot cross the stub.
4. Enable expansion in `config.yaml`:

```yaml
world:
  dynamic_expansion: true
  max_new_rooms_per_session: 5
  require_brief_or_stub: true
```

5. In play, cross the stub (`go west` from the hallway).
6. The runtime validates lore, commits structure under `WorldAuthority`, and emits `room_realized`.
7. Set `dynamic_expansion: false` again. The garden remains.

Play narration never creates rooms. Only stub realize or Builder apply writes structure.

### 4.9 Host small co-op (thin web)

1. Start the server:

```bash
WORLD_SIM_LLM=fake world-sim-serve --host 127.0.0.1 --port 8765
```

2. Open http://127.0.0.1:8765/ in a browser.
3. Log in (signup on first use).
4. Use play text, public **Say**, **Who is here**, and the schematic **Map**.

Two clients:

1. Open two windows or profiles.
2. Sign in as different users.
3. Stand in the same room. Presence should list both names.
4. Race `take brass key` in the foyer. One wins. The other gets a runtime refusal.
5. In the study, one client runs `talk to Mrs. Hale`. The other is refused as busy and does not see private chat lines.

CLI beside the server:

1. Keep `world-sim-serve` running.
2. Run `world-sim` against the same appdir (SQLite WAL).
3. Both clients share one world and one `WorldAuthority`.

Map notes:

- Rooms are nodes. Exits are edges.
- You-are-here marks your room. Fog hides unseen rooms.
- LOD: Near (labels) vs Overview (dim distant nodes).
- Click an adjacent revealed room to send a move intent. The server validates.

For real deploys, terminate TLS in front of the process and use `wss://`.

## 5. Command reference

For parameters and behavior of each command, see [`docs/COMMAND-DETAILS.md`](COMMAND-DETAILS.md).

### 5.1 world-sim (any mode)

| Command | Purpose |
|---------|---------|
| `help` | Show commands for the current mode |
| `mode play` | Enter play |
| `mode edit` | Enter edit (admin) |
| `mode chat` | Enter sandbox chat (admin) |
| `whoami` | Show identity |
| `quit` | Exit |

### 5.2 world-sim · play

| Command | Purpose |
|---------|---------|
| `look` | Full room description |
| `go <direction>` | Move (or realize a stub when expansion is on) |
| `take …` | Take an item in the room |
| `examine …` | Examine item or NPC |
| `wait <minutes>` | Advance world time |
| `inventory` | List carried items |
| `talk to <npc>` / `speak to <npc>` | Start Player Chat with a present NPC |
| `end_chat` | Leave Player Chat (also available as a tool) |

Natural language actions also go to the LLM with tools when not a direct move.

### 5.3 world-sim · edit (admin)

Admin only. Constrained canon maintenance. New rooms, exits, and bulk placements stay in `world-builder`.

Canon **text** lives in ChromaDB. Structured entities, drafts, lore-key refs, and presentation seen-state live in SQLite. Many write commands touch both.

#### 5.3.1 Lore browse (Chroma)

Read approved lore text. Optional `room_id=` / `item_id=` / `search=` filters may look up ids in SQLite, but these commands do not rewrite structure.

| Command | Purpose |
|---------|---------|
| `list_system_lore [search=…]` | List system lore keys (short preview) |
| `view_system_lore <key>` | Show full system lore text |
| `list_room_lore [room_id=…] [search=…]` | List room lore keys |
| `view_room_lore <key>` | Show full room lore text |
| `list_item_lore [item_id=…] [search=…]` | List item definition lore keys |
| `view_item_lore <key>` | Show full item lore text |

#### 5.3.2 Structure / records (SQLite)

Browse or change structured records. These do not replace Chroma lore text (except that `view_npc` may *display* linked lore for reading).

| Command | Purpose |
|---------|---------|
| `list_rooms [search=…]` | List rooms in the world graph |
| `list_items [search=…]` | List item definitions |
| `list_npcs [search=…]` | List NPC records |
| `view_npc <npc_id>` | Show NPC record (and linked lore text for reading) |
| `add_npc <id> \| <name> \| <lore_keys> [--in room]` | Attach existing lore keys to an NPC record |
| `edit_npc <id> \| name=<name>` | Rename NPC (invalidates presentation) |
| `delete_npc <npc_id>` | Remove NPC record (Chroma lore stays) |

#### 5.3.3 Canon writes that bridge both

Write or delete Chroma text and update SQLite (lore-key refs, drafts, presentation invalidation, and/or NPC rows). Canon text still lives in Chroma; link checks and seen-state live in SQLite.

| Command | Purpose |
|---------|---------|
| `add_system_lore <key> \| <text>` | Write system lore + lore-key ref |
| `edit_system_lore …` | Alias of `add_system_lore` (write or replace) |
| `create_system_lore <prompt>` | LLM draft (pending in SQLite) |
| `delete_system_lore <key>` | Delete system lore if unused |
| `add_room_lore <room_id> \| <text>` | Rewrite lore for an existing room; invalidate presentation |
| `edit_room_lore …` | Alias of `add_room_lore` (write or replace) |
| `create_room_lore <room_id> <prompt>` | LLM room lore draft (room must exist) |
| `delete_room_lore <key>` | Delete if no room still links the key |
| `add_item_lore <item_id> \| <text>` | Rewrite lore for an existing definition; invalidate presentation |
| `edit_item_lore …` | Alias of `add_item_lore` (write or replace) |
| `create_item_lore <item_id> <prompt>` | LLM item lore draft (definition must exist) |
| `delete_item_lore <key>` | Delete if no definition still links the key |
| `add_npc_lore <npc_id> \| <text>` | Rewrite primary NPC lore; update record; invalidate presentation |
| `edit_npc_lore …` | Alias of `add_npc_lore` (write or replace) |
| `create_npc_lore <npc_id> <prompt>` | LLM primary NPC lore draft (NPC must exist; freer rewrite; pending) |
| `revise_npc_lore <npc_id> <prompt>` | LLM draft: keep existing primary lore, fold in prompt (pending) |
| `append_npc_lore …` | Alias of `revise_npc_lore` |
| `create_npc <prompt>` | LLM NPC draft (pending) |
| `list_drafts` | List pending/reviewed drafts (SQLite) |
| `view_draft <id>` | Show draft body |
| `approve_draft <id>` | Commit draft to Chroma (+ NPC/refs as needed); invalidate presentation |
| `reject_draft <id>` | Reject draft without making canon |

Notes:

- `create_*` stores a pending draft only. `approve_draft` makes it canonical.
- `add_*_lore` / `edit_*_lore` are the same explicit admin upsert (write or replace; no draft). `add_*` remains the canonical spelling.
- `edit_npc` renames the SQLite record only. Lore text uses `add_npc_lore` / `edit_npc_lore`.
- Bulk rooms, exits, and placements stay in `world-builder`.

### 5.4 world-builder

| Command | Purpose |
|---------|---------|
| `help` | Show Builder help |
| `list_lore [system\|room\|item\|npc]` | Browse approved Chroma lore |
| `upsert_lore <lore_key> \| <text>` | Write Chroma lore (no SQLite structure yet) |
| `discover_lore <query…>` | Semantic discovery when `retrieval.enabled` |
| `propose_discovered <rooms\|items\|npcs> <query…> [--in room]` | Propose from grounded hits only |
| `propose_rooms_from_lore` / `propose_items_from_lore` / `propose_npcs_from_lore` | Draft from keys |
| `propose_from_brief <path>` | Draft from guidance brief + current lore |
| `connect_rooms` / `place_item` / `place_npc` | Edit draft links and placements |
| `attach_room_lore` / `attach_item_lore` / `attach_npc_lore` | Attach lore on the draft |
| `preview_seed_plan` | Show draft effects |
| `validate_world` | Check world and/or draft |
| `apply_seed_plan` | Commit draft to SQLite (explicit) |
| `add_frontier_stub` / `list_frontier_stubs` | Prepare / list unrealized exits |
| `list_plans` / `open_plan` | Manage saved plans |
| `quit` / `exit` | Leave Builder |

### 5.5 world-sim-serve

| Surface | Purpose |
|---------|---------|
| `GET /` | Thin web client |
| `POST /api/login` | Auth (token for WebSocket) |
| `WS /ws?token=…` | Play actions, say, move, map, presence |
| Map panel | Schematic graph (fog, LOD, you-are-here) |

Example WebSocket messages after login:

```json
{"type": "action", "text": "look"}
{"type": "say", "text": "Hello"}
{"type": "move", "direction": "north"}
{"type": "get_map", "lod": "near"}
{"type": "get_presence"}
```

## 6. Configuration switches

Default `config.yaml` keys operators change most often:

```yaml
provider: grok
chat_npc_id: mrs_hale
logging:
  level: INFO
world:
  dynamic_expansion: false
  max_new_rooms_per_session: 5
  require_brief_or_stub: true
memory:
  enabled: false
  max_per_subject: 20
  max_summary_chars: 280
  ttl_days: 0
retrieval:
  enabled: false
  top_k: 5
  play_context: true
  builder_discover: true
player_chat:
  lore_guard: false
  max_regenerations: 1
```

| Key | Default | Effect |
|-----|---------|--------|
| `world.dynamic_expansion` | false | Allow stub realize on cross |
| `memory.enabled` | false | Bounded runtime memory |
| `retrieval.enabled` | false | Semantic assist (Builder / play context) |
| `player_chat.lore_guard` | false | Judge Player Chat replies vs must/must_not + NPC lore |

Optional `player_chat.must` / `player_chat.must_not` lists override built-in policy lines. On fail: regenerate up to `max_regenerations`, then refuse in character.

Secrets in `.env`:

```dotenv
GROK_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
ADMIN_PASSWORD=
```

Supported providers: `grok` (default), `openai`, `anthropic`. Set the matching API key.

## 7. Operator checklist

Before a session:

1. Confirm `.env` keys for the chosen provider (or use `WORLD_SIM_LLM=fake`).
2. Confirm `config.yaml` switches match the session (expansion / memory / retrieval).
3. Prefer a fixed world (`dynamic_expansion: false`) for playtests.
4. Use Builder for new rooms. Use edit_mode for small canon fixes.

During co-op:

1. One world DB. Same appdir for CLI and serve.
2. Expect one winner on contested takes and exclusive chat leases.
3. Do not treat map clicks or retrieval text as authority. The server decides.

After Builder apply:

1. Run `validate_world` before apply when the plan is large.
2. Play the new graph in `world-sim` or the thin web.
3. Keep Exp-001–008 off unless you explicitly enable an experiment later.

## 8. Related documents

| Doc | Use |
|------|-----|
| `README.md` | Install, status, sample flows |
| `docs/README.md` | Docs index (operator + design) |
| `docs/WORLD-AUTHORING.md` | Step-by-step world-authoring tutorial (small wing) |
| `docs/COMMAND-DETAILS.md` | Per-command detail (section 5 expanded) |
| `docs/cache/COMMAND-MATRIX.md` | Compact command table |
| `docs/cache/SPEC-PLAYER-CHAT.md` | Player Chat contract (incl. optional lore guard) |
| `docs/cache/BUSINESS-RULES.md` | Canon vs runtime rules |
| `docs/cache/SPEC-WORLD_BUILDER.md` | Builder contract |
| `docs/cache/SPEC-PLAYER-CHAT.md` | Player Chat rules |
| `docs/cache/SPEC-MULTIPLAYER.md` | Co-op arbitration and privacy |
| `docs/cache/CLIENT-WEB.md` / `CLIENT-MAP.md` | Thin web and map |
| `docs/cache/EXPERIMENTAL.md` | Post–final-shape experiments (not default ops) |
| `docs/cache/SCALING.md` | Capacity beyond small co-op (not required) |
