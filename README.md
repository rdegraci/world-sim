# World-Sim

World-Sim is a Python narrative simulation project. Today, the repository provides a packaged `world-sim` command that starts a local CLI session shell. The project is intended to grow into a local app with onboarding, SQLite-backed runtime state, ChromaDB-backed canonical lore, multi-provider LLM support, admin tooling, and a companion world-building workflow.

## Status

Slices 1–3 are implemented. Later MVP slices still ahead.

### Implemented now

- Packaged CLI command: `world-sim`
- Appdir bootstrap, `.env` / `config.yaml`, startup logging
- Auth (signup/login + admin from `ADMIN_PASSWORD`)
- SQLite world structure: rooms, exits, item definitions/instances, inventories, sessions, transcripts, presentation state
- ChromaDB canonical lore by stable keys with explicit SQLite lore-key refs
- Seeded Quiet Manor starter world
- Grounded `play_mode` loop (context → LLM → tools → persist → reply)
- Grok adapter by default; `WORLD_SIM_LLM=fake` for offline play/tests

### Planned MVP direction

- Admin `chat_mode` and constrained `edit_mode`
- OpenAI / Anthropic provider expansion
- Companion `world-builder` workflow
- Optional WebSocket / networked clients after the local CLI runtime is solid

## Features

### Available today

- Local signup/login and admin auth
- Grounded play in the Quiet Manor (move, take, look, examine, wait)
- Room/item full description vs stable recap presentation
- False unsupported claims refused in-character (no invented ontology)

### Planned for later MVP slices

- Admin `chat_mode` for sandboxed NPC testing
- Admin `edit_mode` for constrained canonical content management
- Broader multi-provider support beyond Grok

## Project Structure

```text
.
├── LICENSE
├── README.md
├── dev-requirements.txt
├── docs/
├── pyproject.toml
└── world_sim/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py
    ├── config.py
    ├── auth/
    ├── db/
    ├── llm/
    ├── lore/
    ├── models/
    ├── orchestrator/
    ├── prompts/
    ├── server/
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

Runtime dependencies include `platformdirs`, `python-dotenv`, `PyYAML`, `chromadb`, and `openai` (for the Grok-compatible API client). FastAPI/WebSockets remain deferred.

## Usage

On first run, World-Sim creates platformdirs locations for the `world-sim` app, writes a default `config.yaml`, writes a `.env` template if missing, and initializes SQLite + Chroma storage.

1. Install the package (`pip install -e .`).
2. Run `world-sim` once so bootstrap can create the app directories and `.env` template.
3. Edit the generated `.env` and set:
   - `GROK_API_KEY` (required unless using offline fake LLM)
   - `ADMIN_PASSWORD` (required only if you log in as `admin`)
4. Run `world-sim` again.

Offline / test play without calling Grok:

```bash
WORLD_SIM_LLM=fake world-sim
```

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

The project is also intended to include a companion subsystem named World Builder.

World Builder is intended to:
- seed structured SQLite entities from approved lore
- attach explicit lore-key references
- preview proposed changes before applying them
- validate cross-store consistency between SQLite and ChromaDB
- support room topology, placements, linking, reconciliation, and maintenance workflows

The recommended strategy is lore-first but structure-reviewed:
1. create canonical lore in ChromaDB
2. create structured entities in SQLite explicitly
3. attach lore-key references
4. optionally use an LLM to propose structures
5. require admin review before saving

## Configuration

Slice 1 resolves paths with `platformdirs` for the `world-sim` app:
- **Config directory**: `.env` and `config.yaml`
- **Data directory**: `world_sim.sqlite3` and `chroma/` (path-level init only)

On platforms where config and data resolve to the same directory, runtime files are kept under a `data/` subdirectory so secrets/config stay separate from storage.

Default `config.yaml`:

```yaml
provider: grok
grok_model: grok-4.5
logging:
  level: INFO
```

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

Near-term likely work:
- Slice 4: constrained admin `edit_mode`
- Slice 5: sandboxed admin `chat_mode` and Phase 1 completion
- later: World Builder, then networked clients / multiplayer

## License

Copyright 2026 Rodney Degracia

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
