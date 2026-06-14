# PriorStates — Quickstart

PriorStates gives Claude, Codex, and Gemini a shared local **memory**, a durable
**research journal**, runnable-Markdown (**mdlab**), and a **cockpit** website —
plus a **desktop GUI** to manage it all. Everything runs on your machine.

## 1. Install

Grab an installer for your OS at **<https://priorstates.com/install>** — all
**per-user, no root/admin**:

- **Linux** — `.deb`/`.rpm` (app-menu launcher; uses `sudo`), or the no-root one-liner.
- **macOS** — the `.pkg` ("install for me only" — no admin password; signed & notarized).
- **Windows** — `Setup.exe` (no admin), or `pipx install priorstates` if `.exe` is blocked.

Or use Python directly (any OS, no installer):

```bash
pip install -U priorstates          # or: pipx install priorstates
# …or one command on Linux/macOS (installs, initializes, wires agents):
curl -fsSL https://priorstates.com/install.sh | sh
```

Then initialize and wire your agents:

```bash
priorstates init                    # ~/.priorstates/ (global) + ./.priorstates/ (this project)
priorstates agents install          # wire Claude / Codex / Gemini over MCP
```

**`python3 -m priorstates` always works** regardless of PATH; the bare
`priorstates` command works once your user scripts dir (e.g. `~/.local/bin`) is on
`PATH`.

No model download is required: memory works immediately with a built-in
**hashing embedder**. Run `priorstates init --download-model` (≈127 MB) to upgrade
to semantic recall.

## 2. The two surfaces

### Desktop GUI (manage everything)

```bash
priorstates gui
```

Tabs: **Dashboard** (status + launch cockpit + reindex + download model),
**Memory** (search/add/pin/delete), **Journal** (search/add), **Agents**
(install/uninstall + status), **mdlab** (pick a file and Run).

### Cockpit (browse in a browser)

```bash
priorstates cockpit          # → http://127.0.0.1:7700
```

Read-only map of the journal (group by topic/outcome/date) and memory
(pinned-first), with in-app Markdown rendering.

## 3. CLI cheatsheet

```bash
# memory
priorstates memory add prefers-bullets --type preference --pin \
    --description "short PRs" --body "Keep PR bodies to 3-5 bullets."
priorstates memory search "pull request style"
priorstates memory list

# journal
priorstates journal add --topic auth --outcome winner \
    --title "httpOnly cookies cut XSS" --body "**TL;DR**: moved token to cookie."
priorstates journal search --topic auth
priorstates journal regen          # rebuild INDEX.md + by_topic/ + digests/

# runnable markdown
priorstates mdlab run notes.mdlab.md

# status / agents
priorstates doctor
priorstates agents status
```

## 4. How agents use it (the research loop)

Once wired, each agent sees PriorStates's MCP tools (`memory_search`,
`memory_add`, `journal_search`, `journal_add`, `journal_regen`, `mdlab_run`,
plus `memory_get/pin/list_pinned/delete`) and the **pinned memory block** in its
context file (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`).

The intended loop — both interactive and autonomous:

1. **Recall** — before proposing work, the agent runs `journal_search` ("has
   this been tried? was it a loser?") and `memory_search` (preferences,
   project facts).
2. **Act** — it does the work in its normal session.
3. **Record** — on a durable conclusion it calls `journal_add`
   (winner/loser/bug/decision/…); on a learned preference it calls `memory_add`.

`priorstates agents install` writes this as a standing instruction automatically —
the **research-protocol block** in each agent's context file (toggle with
`priorstates agents protocol` / `--off`, or skip at install with `--no-protocol`).

**Where to create research folders, and the three ways entries get added, are
covered in detail in [RESEARCH_WORKFLOW.md](RESEARCH_WORKFLOW.md).**

## 5. mdlab blocks

Inside any `*.mdlab.md` (or `.md`):

~~~markdown
```python
x = 6 * 7          # state persists across python blocks in the file
print(x)
```

```bash
echo "shell blocks run too"
```

```journal
---
topic: my-feature
outcome: winner
title: one-line finding
---
**TL;DR**: what happened, with the number.
```

```journal-search {topic=my-feature}
```
~~~

`priorstates mdlab run file.mdlab.md` executes the runnable blocks and writes
results back into `<!-- priorstates:result ... -->` regions (idempotent;
`{cache=true}` skips unchanged blocks).

## 6. Where your data lives

```
~/.priorstates/                 global scope
  config.toml                machine config (model, agents, outcomes, backup)
  memory/*.md                global memories (identity/preferences)
  memory.psmem                derived search index
  models/                    embedding model (after --download-model)

<project>/.priorstates/         project scope (created by `priorstates init`)
  memory/*.md                project memories
  journal/INDEX.md           the journal (+ entries/, by_topic/, digests/)
  journal.psmem               derived journal search index
```

All plain Markdown — `grep` it, `git` it, edit it. Delete a `.psmem` and it
rebuilds. Uninstall cleanly with `priorstates agents uninstall`.
