# World-Sim

World-Sim is a Python narrative simulation project. Today, the repository provides a packaged `world-sim` command that starts a local CLI session shell. The project is intended to grow into a local app with onboarding, SQLite-backed runtime state, ChromaDB-backed canonical lore, multi-provider LLM support, admin tooling, and a companion world-building workflow.

## Status

Slice 1 (local app skeleton) is implemented. Later MVP slices still ahead.

### Implemented now

- Packaged CLI command: `world-sim`
- Module entry points: `python -m world_sim` and `python -m world_sim.cli`
- Appdir bootstrap with `platformdirs`
- Secret loading from `.env` and tuning from `config.yaml`
- Path-level SQLite and ChromaDB storage initialization
- Startup logging
- Local interactive session shell (help / quit)

### Planned MVP direction

- Username onboarding and password-based login
- SQLite schemas for users, world, and runtime state
- ChromaDB collections for canonical lore
- Provider adapters for Grok, OpenAI, and Anthropic
- `play_mode`, admin `chat_mode`, and constrained `edit_mode`
- A companion `world-builder` workflow for world seeding and validation
- Optional WebSocket / networked clients after the local CLI runtime is solid

## Features

### Available today

- Packaged CLI command: `world-sim`
- First-run bootstrap of config and data directories
- Required `GROK_API_KEY` validation before the session starts
- Local session shell with `help` and `quit`

### Planned for later MVP slices

- Username onboarding and password-based login
- SQLite-backed user and world storage schemas
- Admin login with credentials sourced from `.env`
- Grok-backed `play_mode` by default
- Admin `chat_mode` for sandboxed NPC testing
- Admin `edit_mode` for constrained canonical content management
- Provider support for OpenAI, Anthropic, and Grok through an internal adapter layer
- Canonical lore storage in ChromaDB with explicit lore-key linking from SQLite

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
    ├── db/
    ├── models/
    ├── orchestrator/
    ├── prompts/
    ├── server/
    │   └── session_server.py
    ├── tools/
    └── utils/
        └── logger.py
```

## Requirements

- Python 3.11+
- `pip`

## Installation

Clone the repository and install it in editable mode:

```bash
pip install -e .
```

Runtime dependencies for Slice 1 include `platformdirs`, `python-dotenv`, and `PyYAML`. SQLite helpers, ChromaDB, and LLM SDKs will be added in later slices. FastAPI/WebSockets remain deferred until after the local CLI runtime.

## Usage

On first run, World-Sim creates platformdirs locations for the `world-sim` app, writes a default `config.yaml`, writes a `.env` template if missing, and creates SQLite/Chroma path placeholders under the data directory.

1. Install the package (`pip install -e .`).
2. Run `world-sim` once so bootstrap can create the app directories and `.env` template.
3. Edit the generated `.env` and set a non-empty `GROK_API_KEY`.
4. Run `world-sim` again.

```bash
world-sim
```

Or run a module entry point:

```bash
python -m world_sim
python -m world_sim.cli
```

You should see startup logs on stderr, then a local prompt:

```text
World-Sim local session
Type 'help' for commands, or 'quit' to exit.

>
```

Type `help` for available commands, or `quit` / `exit` to leave.

If `GROK_API_KEY` is missing or empty, startup exits with a clear configuration error before the session loop starts.

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
- Slice 1: local app skeleton (appdir, `.env`, `config.yaml`, storage paths, session shell)

Near-term likely work:
- Slice 2: onboarding and authentication
- Slice 3: grounded play loop with SQLite + ChromaDB lore keys
- Slice 4: constrained admin `edit_mode`
- Slice 5: sandboxed admin `chat_mode` and Phase 1 completion
- later: World Builder, then networked clients / multiplayer

## License

Copyright 2026 Rodney Degracia

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
