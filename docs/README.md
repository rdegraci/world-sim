# docs — Operator and design documentation

Living operator docs live here. Design contracts and build prompts live under `cache/`.

## Start here

| Goal | Doc |
|------|-----|
| Install / status / sample flows | [`../README.md`](../README.md) |
| Day-to-day ops (play, edit, serve, config) | [`OPERATOR.md`](OPERATOR.md) |
| Step-by-step author a small wing | [`WORLD-AUTHORING.md`](WORLD-AUTHORING.md) |
| Full command syntax and parameters | [`COMMAND-DETAILS.md`](COMMAND-DETAILS.md) |
| One-page command cheat sheet | [`cache/COMMAND-MATRIX.md`](cache/COMMAND-MATRIX.md) |
| Design specs, phases, experiments | [`cache/README.md`](cache/README.md) |

## Living docs (this folder)

| Doc | Role |
|-----|------|
| `OPERATOR.md` | Use cases, modes, co-op hosting, config switches |
| `WORLD-AUTHORING.md` | Ordered tutorial: 2 rooms, NPC, table + book |
| `COMMAND-DETAILS.md` | Per-command detail (expands OPERATOR §5) |

## Design cache (`cache/`)

Do not treat `cache/` prompts as “still to build” for shipped phases. See `cache/README.md` **Final Shape Snapshot** for what is implemented vs deferred.

Notable optional runtime switches (all default **off** unless noted):

| Key | Meaning |
|-----|---------|
| `world.dynamic_expansion` | Realize frontier stubs on cross |
| `memory.enabled` | Bounded per-character memory (4b1) |
| `retrieval.enabled` | Semantic assist for Builder / play context (4b2) |
| `player_chat.lore_guard` | Judge Player Chat replies vs must/must_not + NPC lore |

Tune `player_chat.must` / `player_chat.must_not` / `max_regenerations` when the lore guard is on.
