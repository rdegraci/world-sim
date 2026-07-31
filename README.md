# World-Sim

World-Sim is a Python narrative simulation project. Today, the repository provides a packaged `world-sim` command that starts a local CLI session shell. The project is intended to grow into a local app with onboarding, SQLite-backed runtime state, ChromaDB-backed canonical lore, multi-provider LLM support, admin tooling, and a companion world-building workflow.

## Status

Slices 1–5 are implemented. Phase 1 MVP platform is complete.

### Implemented now

- Packaged CLI commands: `world-sim`, `world-builder`, `world-sim-serve`
- Appdir bootstrap, `.env` / `config.yaml`, startup logging
- Auth (signup/login + admin from `ADMIN_PASSWORD`)
- SQLite world structure + ChromaDB canonical lore with lore-key refs
- Seeded Quiet Manor + Mrs. Hale NPC
- Grounded `play_mode`, admin `edit_mode`, admin sandboxed `chat_mode`
- World Builder companion: propose / preview / validate / apply (+ `propose_from_brief`)
- Richer admin `edit_mode`: `create_room_lore` / `create_item_lore` / `create_npc` drafts, list filters, delete guards
- Focused in-play Player Chat (`talk to <npc>` / `end_chat`) — conversation-only
- Optional dynamic frontier expansion (`world.dynamic_expansion`, default off) with campaign identity
- Phase 3a: `WorldAuthority` port over play mutations + scene-public runtime event bus (map/presence substrate)
- Phase 3b: `world-sim-serve` multi-session WebSockets, in-room presence, public `say`, thin web + schematic map
- Phase 4a: serial mutation queue, claim locks, exclusive Player Chat leases, private transcripts
- Phase 4b1 (optional): bounded per-character / NPC-about-player memory (`memory.enabled`, default off)
- Providers: Grok (default), OpenAI, Anthropic; `WORLD_SIM_LLM=fake` for offline tests

### Deferred after MVP

- Nice web / admin web polish (Phase 3b+ / CLIENT-WEB Tier B)
- Scale-out beyond small co-op (`docs/cache/SCALING.md`)
- Broad CRUD / large-scale world editing beyond Builder + edit_mode
- Semantic retrieval assist (Phase **4b2**, independently optional after 4a)
- Player Chat inventory handoff / barter
- Unsupervised Builder apply (Exp-007); dig-style room features (Exp-001)
- Experiments Exp-001–008 (`docs/cache/EXPERIMENTAL.md`) — not part of 4b1

## Project Structure

```text
.
├── LICENSE
├── README.md
├── dev-requirements.txt
├── docs/
├── examples/
│   └── seed-brief-cellar.yaml
├── pyproject.toml
└── world_sim/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py
    ├── config.py
    ├── auth/
    ├── authority/
    ├── builder/
    ├── db/
    ├── llm/
    ├── lore/
    ├── models/
    ├── orchestrator/
    ├── prompts/
    ├── server/          # CLI session loop + Phase 3b web/WS
    ├── tools/
    └── utils/
```

## Requirements

- Python 3.11+
- `pip`

## Installation

Clone the repository and install it in editable mode:

```bash
pip install -e .
```

Runtime dependencies include `platformdirs`, `python-dotenv`, `PyYAML`, `chromadb`, `openai` / `anthropic`, and `fastapi` + `uvicorn` (Phase 3b multi-session server).

## Usage

On first run, World-Sim creates platformdirs locations for the `world-sim` app, writes a default `config.yaml`, writes a `.env` template if missing, and initializes SQLite + Chroma storage.

1. Install the package (`pip install -e .`).
2. Run `world-sim` once so bootstrap can create the app directories and `.env` template.
3. Edit the generated `.env` and set:
   - `GROK_API_KEY` (required unless using offline fake LLM)
   - `ADMIN_PASSWORD` (required only if you log in as `admin`)
4. Run `world-sim` again (CLI) and/or `world-sim-serve` (thin web).

Offline / test play without calling Grok:

```bash
WORLD_SIM_LLM=fake world-sim
```

### Multi-session thin web (Phase 3b)

Same appdir SQLite/Chroma world as the CLI. Start the server:

```bash
WORLD_SIM_LLM=fake world-sim-serve --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765/** — login (signup on first use), play text, public **Say**, **Who is here** presence, and the schematic **Map**.

- **Two browser clients:** open two windows/profiles, sign in as different users; both should see each other under **Who is here** when in the same room; a `take` or `say` in that room fans out as a scene event (not a shared transcript).
- **CLI + web:** run `world-sim` against the same appdir while `world-sim-serve` is up (SQLite WAL). Both use `WorldAuthority` / the same DB. Contested races harden in Phase 4a — avoid simultaneous writes to the same item until then.
- **Presence:** live connections in your current room (display names). Leaving the room removes you from that roster for others.
- **Map:** right-hand SVG graph (rooms = nodes, exits = edges). Yellow/you-are-here marks your room; blue dots are other players on revealed rooms. Fog hides rooms you have not seen. LOD select: **Near** (labels) vs **Overview** (dim distant nodes). Click an **adjacent** revealed room to send a move intent (`go <direction>`); the server validates.
- **WSS:** terminate TLS in front of uvicorn for real deploys (`wss://…`); local default is `ws://`.
- **Player Chat:** `talk to <npc>` uses an exclusive WorldAuthority lease. A second client sees the NPC as engaged/busy and is refused — private chat text never fans out. Presence includes `busy_npcs`.

### Contested co-op demo (Phase 4a)

1. Start the server: `WORLD_SIM_LLM=fake world-sim-serve --port 8765`
2. Open two browser windows at http://127.0.0.1:8765/ and sign in as different users (or use one browser + `world-sim` CLI on the same appdir).
3. **Race a take:** both stand in the foyer; both type `take brass key`. One gets the item; the other gets a structured runtime refusal (not an LLM-invented win). Observers in the room may see a scene `item_taken` event.
4. **Compete for chat:** both go to the study; one types `talk to Mrs. Hale`. The other tries the same and is told she is engaged — without receiving the first player's private transcript lines.
5. Map you-are-here stays on the server room after moves; failed takes do not move inventory.

WebSocket tip (after `POST /api/login`): connect to `/ws?token=<token>` with JSON messages `{ "type": "action", "text": "look" }`, `{ "type": "say", "text": "…" }`, `{ "type": "move", "direction": "north" }`, `{ "type": "get_map", "lod": "near" }`, `{ "type": "get_presence" }`.

After login you start in the Quiet Manor foyer. Useful actions:

```text
look
go north
take brass key
examine brass key
go east
wait 10
inventory
```

Admin canon editing (after logging in as `admin`):

```text
mode edit
list_rooms
list_room_lore search=foyer
create_room_lore foyer Mention damp coats by the door
list_drafts
view_draft 1
approve_draft 1
mode play
look
```

After `approve_draft`, the next encounter/look uses the **full** canonical description again (recap + seen-state invalidated).

Other Phase 2b edit paths:

```text
mode edit
create_item_lore brass_key Emphasize a scratched numeral
create_npc A gardener who tends the courtyard pots
approve_draft 2
add_npc gardener | Gardener | npc:gardener:description --in foyer
add_room_lore foyer | Direct rewrite without LLM
create_system_lore A note about the manor's evening bell
approve_draft 3
mode play
```

LLM-assisted `create_*` commands stay drafts until `approve_draft`. Bulk rooms/exits/placements stay in `world-builder`.

Admin sandboxed NPC chat:

```text
mode chat
Hello, Mrs. Hale.
who
mode play
go north
go east
examine mrs hale
```

Focused in-play Player Chat (any player; present NPC only — not admin `chat_mode`):

```text
go north
go east
talk to Mrs. Hale
What do you know about this study?
end_chat
look
```

While talking, the prompt is `talk>` and lines go to that NPC. `end_chat` returns to normal play. No inventory transfers happen inside this loop.

```bash
world-sim
```

Or run a module entry point:

```bash
python -m world_sim
python -m world_sim.cli
```

Startup authenticates before the session loop:

```text
Sign in to World-Sim.
Enter a username. Use 'admin' for the local admin account.
Username: morgan
Create password: ********
Confirm password: ********
World-Sim local session — signed in as morgan (player)
...
>
```

- New usernames create an account and one linked `player_character`.
- Existing usernames prompt for the stored password hash verification.
- Username `admin` authenticates against `ADMIN_PASSWORD` from `.env` (not a SQLite password hash).

Type `help` for available commands, `whoami` for the current identity, or `quit` / `exit` to leave.

If `GROK_API_KEY` is missing or empty, startup exits with a clear configuration error before authentication.

## Architecture Overview

The intended MVP architecture is centered on a clear separation between structured runtime state and canonical lore.

### Storage model

The project is designed around a split storage model:
- SQLite stores authoritative structured data such as users, player characters, rooms, items, NPC entities, sessions, relationships, runtime state, and explicit lore-key references.
- Play-tool mutations and authoritative structured reads used by tools go through `WorldAuthority` (SQLite-backed today via `WorldStore`). Scene-public runtime events (`character_entered_room`, `item_taken`, `room_realized`, …) persist for later map/presence clients; the CLI may ignore fan-out for now.
- ChromaDB stores canonical lore text such as system lore, room lore, item lore, and canonical NPC lore text.

A useful rule of thumb is:
- SQLite answers what exists, where it is, and how it is connected.
- ChromaDB answers what it means.

### Lore hierarchy

The intended grounding hierarchy is:
1. system lore
2. room lore
3. item lore
4. NPC lore
5. mutable runtime state

### Runtime modes

The docs define three main runtime modes:
- `play_mode` for normal gameplay
- `chat_mode` for admin-only sandboxed NPC conversation
- `edit_mode` for admin-only constrained canonical content management

`chat_mode` is intended to be non-canonical and should not mutate world state or persistent NPC memory.

## World Builder

`world-builder` is a sibling CLI that shares the same appdir, `config.yaml`, `.env`, SQLite DB, and Chroma store as `world-sim`. It seeds and validates **structure** from **approved** Chroma lore. Proposals stay drafts until you explicitly `apply_seed_plan`.

`edit_mode` in World-Sim remains for constrained runtime admin canon ops. Builder owns larger structural seeding (rooms, links, placements, validation).

### Run beside World-Sim

```bash
pip install -e .
world-builder
```

Uses the same paths as `world-sim` (platformdirs `world-sim` config/data). Plans are stored under `<data_dir>/builder/plans/`.

### Sample flow: lore → brief → draft → preview → validate → apply → play

1. Ensure Quiet Manor is seeded (`world-sim` or `world-builder` once).
2. In `world-builder`, approve the lore keys the brief will use (**lore first**; this does not create rooms yet):

```text
upsert_lore room:cellar | The cellar is a cool stone room under the hallway, with packed earth corners and a single oil-stained shelf.
upsert_lore item:oil_lantern | An oil lantern with a soot-dark chimney and a brass handle worn smooth.
list_lore room
```

3. Reuse `examples/seed-brief-cellar.yaml` (goal, caps, must-link / do-not — **intent only, not canon**).
4. Propose structure from the brief:

```text
propose_from_brief examples/seed-brief-cellar.yaml
preview_seed_plan
validate_world
apply_seed_plan
```

`propose_from_brief` writes a **draft** plan only. Preview shows what would change. Apply asks you to type `apply` (or pass `--yes`) before writing SQLite.

5. Play the new structure:

```bash
WORLD_SIM_LLM=fake world-sim
```

```text
look
go north
go down
look
examine oil lantern
```

If the brief names lore keys that are not in Chroma, Builder fails closed (gaps on the plan; validate/apply refuse). Approved lore wins over brief intent; brief facts never silently become canon.

Useful Builder commands: `upsert_lore`, `propose_rooms_from_lore`, `propose_items_from_lore`, `propose_npcs_from_lore`, `connect_rooms`, `place_item`, `place_npc`, `attach_*_lore`, `add_frontier_stub`, `list_frontier_stubs`, `validate_world`, `list_lore`, `list_plans`.

Ungated LLM auto-apply is **not** part of Phase 2a (see `docs/cache/EXPERIMENTAL.md` Exp-007).

### Dynamic frontier expansion (Phase 2d, default off)

Authoring loop:

1. Build and playtest a small fixed world with `world.dynamic_expansion: false` (default).
2. Approve lore for a future room, then register a prepared stub in `world-builder`:

```text
upsert_lore room:garden | A walled kitchen garden of damp earth and clipped rosemary.
add_frontier_stub hallway west --to garden --lore room:garden --name "Kitchen Garden" --return east
list_frontier_stubs pending
```

3. With expansion still **off**, play cannot cross the stub (sealed). Existing rooms stay as they are.
4. Enable in `config.yaml`:

```yaml
world:
  dynamic_expansion: true
  max_new_rooms_per_session: 5
  require_brief_or_stub: true
```

5. Cross the stub in play (`go west` from the hallway). The runtime validates lore, commits durable SQLite structure via Builder apply internals, and emits a `room_realized` runtime event.
6. Restart with `dynamic_expansion: false` — the realized garden **remains** (campaign identity). Turning the switch off only stops further realization.

Play narration never creates rooms; only the stub realize path (or Builder apply) writes structure.

## Configuration

Slice 1 resolves paths with `platformdirs` for the `world-sim` app:
- **Config directory**: `.env` and `config.yaml`
- **Data directory**: `world_sim.sqlite3` and `chroma/` (path-level init only)

On platforms where config and data resolve to the same directory, runtime files are kept under a `data/` subdirectory so secrets/config stay separate from storage.

Default `config.yaml`:

```yaml
provider: grok
grok_model: grok-4.5
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
```

Supported providers: `grok` (default), `openai`, `anthropic`. Set the matching API key in `.env`.

Phase **4b1** bounded memory stays off until `memory.enabled: true`. Records are runtime SQLite state (capped, private per character); they do not rewrite Chroma canon. Phase **4b2** semantic retrieval assist remains independently optional.
Example `.env` secrets:

```dotenv
GROK_API_KEY=your_grok_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ADMIN_PASSWORD=your_admin_password_here
```

`GROK_API_KEY` is required while Grok is the configured provider. Other secrets are optional until later slices use them.

## Development

Run the local session:

```bash
world-sim
```

Run tests:

```bash
pip install -e .
pip install -r dev-requirements.txt
pytest
```

Run type checking if and when mypy is added to the environment:

```bash
mypy world_sim
```

## Roadmap

Completed:
- Slice 1: local app skeleton
- Slice 2: auth and minimal structured runtime
- Slice 3: canonical lore and grounded play loop
- Slice 4: controlled admin canon operations
- Slice 5: mode boundaries and Phase 1 completion

Post-MVP / deferred:
- Networked clients / multiplayer, advanced memory, broader CRUD, frontier expansion, Exp-007 unsupervised apply

## License

Copyright 2026 Rodney Degracia

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
