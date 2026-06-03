# PriorStates

### Shared memory & research journal for your AI agents

> PriorStates is an open-source **memory + research journal + cockpit** that turns
> Claude, Codex, and Gemini into persistent, accountable research partners. It
> runs entirely on your machine, CPU-only, with no cloud calls.

🌐 **Website:** [priorstates.com](https://priorstates.com)

Coding agents are amnesiacs. Every session starts cold: they re-derive what you
already taught them, re-run experiments a past session already concluded, and
forget your preferences the moment the context window rolls over. Teams paper
over this with ever-growing `CLAUDE.md` / `AGENTS.md` files that nobody can
search and that blow the context budget.

PriorStates fixes that with three cooperating subsystems that share **one** local
data store across **all** your agents:

| Subsystem | What it is | Generalized from |
|---|---|---|
| **`pm-memory`** | A local, semantic memory store. Durable facts/preferences/project-state the agent can recall by meaning (mmap + ONNX embeddings), plus an always-on "pinned" block injected into every session. | `tools/claude_memory` |
| **`pm-journal`** | A durable, append-only research journal. Every tested hypothesis, winner, loser, bug, and decision becomes a searchable entry so no experiment is run twice. | `tools/workspace/.agent/journal` |
| **`pm-cockpit`** | A zero-dependency local web server + site that maps the journal, memory, and your research docs — search, group, per-topic dashboards. | `tools/research-cockpit` |

A fourth piece, **`pm-agents`**, is the thin adapter/installer that wires the
above into Claude Code, Codex, and Gemini CLI (all via MCP) and renders the
pinned block into each agent's native context file.

The whole point (task #5): the agent **recalls** memory + journal before
proposing the next step, and **records** durable conclusions back — closing an
**interactive** loop for everyday work and an **autonomous** loop for unattended
research runs.

## Status

**v0.1 — working implementation.** The core is built and tested end-to-end
(memory, journal, mdlab, agent wiring, MCP server, cockpit, desktop GUI):

```bash
./install.sh --wire          # install + init + wire Claude/Codex/Gemini
priorstates gui                 # desktop control panel
priorstates cockpit             # web cockpit → http://127.0.0.1:7700
```

Docs:
- **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — the everyday-use manual (install, scopes, memory, journal, agents, mdlab, cockpit, CLI). **Start here.**
- **[docs/QUICKSTART.md](docs/QUICKSTART.md)** — the short install + first-run version.
- **[docs/RESEARCH_WORKFLOW.md](docs/RESEARCH_WORKFLOW.md)** — focused: where to create research folders + how agents add journal entries.
- **[packaging/README.md](packaging/README.md)** — native `.deb` / macOS `.pkg` / Homebrew packages.
- **[docs/DATA_MODEL.md](docs/DATA_MODEL.md)** — on-disk schemas + `.psmem` layout.

What's implemented now:

| Piece | State |
|---|---|
| `pm-core` (`.psmem` store, embedder, indexer, journal engine, config/root-discovery) | ✅ |
| `pm-memory` (add/search/pin/delete + pinned-block render) | ✅ |
| `pm-journal` (CLI + semantic search + INDEX/by_topic/digests) | ✅ |
| **mdlab** (headless runner: python/bash/journal/journal-search + result regions) | ✅ |
| `pm-agents` (Claude/Codex/Gemini MCP wiring + context files, install/uninstall) | ✅ |
| MCP server (10 tools) | ✅ |
| Cockpit (web server + SPA) | ✅ |
| Desktop GUI (Tkinter control panel) | ✅ |
| Semantic model | optional download; **hashing fallback works with zero setup** |
| Embedder daemon / systemd units / autonomous `priorstates research` runner | ⏳ next |

## Design goals (one screen)

- **Local-first & private.** All data under `~/.priorstates/` and per-project
  `.priorstates/`. Embeddings computed by a vendored CPU ONNX model. No network
  except an *optional*, user-configured git backup.
- **Agent-neutral.** One memory store, one journal, surfaced to Claude / Codex /
  Gemini through the open MCP protocol. Switch agents without losing memory.
- **No build step to run.** Python for the core (memory + journal), plain Node
  (no npm install) for the cockpit, exactly as the originals.
- **Config-driven, not path-hardcoded.** A `priorstates.toml` defines roots,
  outcomes, and which agents to wire — nothing assumes a specific workspace.
- **Drop-in for the originals.** The `.cmem`/journal formats and the cockpit SPA
  carry over with minimal change, so the three battle-tested internal tools are
  the reference implementation, not a rewrite.

## License

**Apache-2.0** (permissive + patent grant). See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 Zhendong Qin.
