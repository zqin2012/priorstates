# PriorStates — User Guide

PriorStates gives Claude, Codex, and Gemini a shared, local **memory**, a durable
**research journal**, runnable‑Markdown (**mdlab**), and a **cockpit** website —
managed from a **desktop GUI** or the CLI. Everything runs on your machine; no
cloud calls, no telemetry.

This is the everyday-use manual. See also: [QUICKSTART.md](QUICKSTART.md) (the
short version). One-click native installers — macOS / Windows / Linux — are at
**https://priorstates.com/download**.

## Contents

1. [Install](#1-install)
2. [Concepts: scopes & where research folders go](#2-concepts-scopes--where-research-folders-go)
3. [Wiring your agents](#3-wiring-your-agents)
4. [Memory](#4-memory)
5. [The research journal](#5-the-research-journal)
6. [How agents add journal entries](#6-how-agents-add-journal-entries)
7. [mdlab — runnable Markdown](#7-mdlab--runnable-markdown)
8. [The cockpit (web) and the desktop GUI](#8-the-cockpit-web-and-the-desktop-gui)
9. [CLI reference](#9-cli-reference)
10. [Data locations, Git, backup](#10-data-locations-git-backup)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Install

Get PriorStates from the **[install guide](https://priorstates.com/install)** —
native installers for macOS / Windows / Linux (all per-user, no admin), or
`pip install -U priorstates` / `pipx install priorstates` (any OS with Python 3.10+).

`python3 -m priorstates …` always works regardless of PATH; the `priorstates` command
also works once the user scripts dir (e.g. `~/.local/bin`) is on PATH.

Memory works immediately with a built-in **hashing embedder** — no download.
For semantic recall: `priorstates init --download-model` (~127 MB). For agent (MCP)
integration: install the `mcp` extra (`pip install --user mcp`, or the `[full]`
extra / the package's Recommends).

First-time setup:

```bash
priorstates init               # creates ~/.priorstates and ./.priorstates for this project
priorstates agents install     # wire Claude / Codex / Gemini
priorstates doctor             # verify
```

## 2. Concepts: scopes & where research folders go

PriorStates has two scopes:

| Scope | Location | Holds | Created by |
|---|---|---|---|
| **global** | `~/.priorstates/` | identity + cross-project preferences; the model | `priorstates init` (once) |
| **project** | `<dir>/.priorstates/` | this project's **memory** *and* its **journal** | `priorstates init` **inside `<dir>`** |

The global scope can be split into named **Areas** (`core-dev`, `strategy`,
`ops`, …) so each kind of work gets its own dense memory pack — orthogonal to the
project you're in. See **[Projects & Areas](PROJECTS_AND_AREAS.md)** for the
two-axis model and the GUI Area selector.

**A "research folder" is any directory you run `priorstates init` in.** It creates:

```
<your-folder>/.priorstates/
  memory/            project memories
  journal/
    INDEX.md         chronological index (newest first)
    entries/*.md     one file per finding
    by_topic/  digests/   generated views
  config.toml        optional per-project overrides
```

Scope is resolved by walking **up from the current directory** to the nearest
ancestor containing `.priorstates/`. So an agent reads/writes the journal of **the
workspace it was opened in**.

### Recommended layouts

- **Per repo (default).** `cd ~/code/my-app && priorstates init`. Open that repo in
  your agent and its journal is used automatically.
- **One research workspace.** `mkdir ~/research && cd ~/research && priorstates
  init`, with experiment sub-folders sharing one journal. Group findings with
  each entry's `topic` field (e.g. `auth-refactor`) — no folder-per-topic
  needed.
- **Global memory only.** Skip project `init` if you only want portable
  preferences across agents.

## 3. Wiring your agents

```bash
priorstates agents install            # MCP + pinned memories + research protocol
priorstates agents status             # what's wired
priorstates agents uninstall          # clean removal
```

Supported agents (all speak **MCP**): **Claude Code**, **Codex**, **Gemini CLI**,
and **Google Antigravity** (the agentic VSCode fork — MCP config at
`~/.gemini/antigravity/mcp_config.json`, reads project `AGENTS.md`). `install`
does two things per enabled agent:

1. **Registers the PriorStates MCP server** in the agent's config
   (`~/.claude.json`, `~/.codex/config.toml`, `~/.gemini/settings.json`,
   `~/.gemini/antigravity/mcp_config.json`),
   exposing the tools `memory_search/get/add/delete/pin/list_pinned`,
   `journal_search/add/regen`, and `mdlab_run`.
2. **Writes two managed blocks** into the agent's context file
   (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`):
   - the **pinned-memory block** (your always-relevant memories), and
   - the **research-protocol block** (the standing instruction to use the
     journal — see §6).

Everything you write *outside* the `<!-- BEGIN/END priorstates: … -->` markers is
preserved. Choose which agents are wired in `~/.priorstates/config.toml`
(`[agents] enabled = [...]`).

## 4. Memory

Durable facts the agent can recall by meaning. Types: `user` (identity),
`preference` (how you like work done), `project` (project state/constraints),
`reference` (links), `note`.

```bash
priorstates memory add prefers-bullets --type preference --pin \
  --description "short PRs" --body "Keep PR bodies to 3-5 bullets, no preamble."
priorstates memory search "pull request style"
priorstates memory list                 # pinned memories
priorstates memory pin prefers-bullets --unpin
priorstates memory delete prefers-bullets
```

- **Scope:** `--scope project` (default) or `global`. Put identity/preferences
  in `global`, project facts in `project`.
- **Pinned** memories are injected into every agent session (the pinned block).
- Agents do the same via the `memory_add` / `memory_search` MCP tools.

## 5. The research journal

An append-only record of findings — one entry per durable conclusion — so no
experiment is run twice. Entry fields:

| field | required | notes |
|---|:--:|---|
| `topic` | ✓ | stable kebab-case area, e.g. `auth-refactor` |
| `outcome` | ✓ | `winner · decision · gotcha · bug · loser · inconclusive · note` |
| `title` | ✓ | one line |
| `body` | ✓ | start with `**TL;DR**:` and the headline result/number |
| `tags`, `evidence`, `supersedes` | – | optional; `supersedes` = a prior entry id (auto-marks it) |

```bash
priorstates journal add --topic auth-refactor --outcome winner \
  --title "httpOnly cookies cut XSS" \
  --body "**TL;DR**: moved the session token to an httpOnly+SameSite cookie; p95 unchanged." \
  --tag security --evidence PR#412

priorstates journal search --topic auth-refactor
priorstates journal search --query "token theft" --outcome loser   # semantic + filter
priorstates journal regen          # rebuild INDEX.md + by_topic/ + digests/
```

Outcomes are configurable per project in `.priorstates/config.toml`
(`[journal] outcomes = [...]`).

## 6. How agents add journal entries

Three ways — you'll use all three.

### a) The agent records on its own (main path)

`priorstates agents install` writes the **research-protocol block** into each
agent's context file. It instructs the agent to:

1. `journal_search` **before** non-trivial work (don't repeat a known *loser* or
   contradict a recorded *decision*), and `memory_search` for relevant context;
2. `journal_add` **when it reaches a durable conclusion**;
3. `memory_add` when it learns a durable preference/fact.

So once wired, agents journal as they work. Manage the instruction separately:

```bash
priorstates agents install --no-protocol    # wire tools but skip the instruction
priorstates agents protocol                 # (re)write just the protocol block
priorstates agents protocol --off           # remove just the protocol block
```

### b) You ask, in-session

> "Record that in the journal — topic `auth-refactor`, outcome `winner`."
> "What does the journal say about token storage?"

→ the agent calls `journal_add` / `journal_search`.

### c) Manually — CLI or mdlab

The `priorstates journal add` command (above), or a fenced `journal` block in an
mdlab doc (next section).

## 7. mdlab — runnable Markdown

Any `*.mdlab.md` (or `.md`) can contain runnable blocks. `priorstates mdlab run
FILE` executes them and writes results back into `<!-- priorstates:result … -->`
regions (idempotent; `{cache=true}` skips unchanged blocks).

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

```bash
priorstates mdlab run notes.mdlab.md
```

`journal` blocks publish an entry; `journal-search` blocks render a results
table. The MCP `mdlab_run` tool lets agents run files too.

## 8. The cockpit (web) and the desktop GUI

**Cockpit** — a read-only browser map of your journal + memory:

```bash
priorstates cockpit                 # → http://127.0.0.1:7700
priorstates cockpit --port 8080
```

Three tabs: **Journal** (group by topic/outcome/date), **Docs** (your project's
research Markdown files, grouped by folder — e.g. `UFO_1/`, `experiments/`), and
**Memory** (pinned first), all with in-app Markdown rendering and back/forward.
Over SSH, forward the port rather than binding `0.0.0.0`.

**Open in editor.** Start it with `priorstates cockpit --allow-open` and each
rendered doc/entry gets *Open in VSCode / Antigravity / …* buttons (only for
editors whose CLI is on PATH). Clicking launches that editor on the cockpit host
at the file — which, under VSCode/Antigravity **Remote-SSH**, opens it in your
attached window. It's opt-in (off by default) since it runs a process on the
host; the path is confined to the workspace. For the button to reach your
window, launch the cockpit from your editor's integrated terminal so it inherits
the remote `code`/`antigravity` shim.

**Desktop GUI** — a control panel for everything:

```bash
priorstates gui                     # or the "PriorStates" app from your menu (.deb/.pkg)
```

Tabs: **Dashboard** (status + launch cockpit + reindex + download model),
**Memory**, **Journal**, **Agents** (install/uninstall + status), **mdlab**
(pick a file → Run). Needs Tk (`python3-tk` on Debian/Ubuntu).

**Workspaces (left sidebar).** Each open workspace — **local** or **remote** — is
a tab down the left side; click one to switch, `✕` to close. **+ Add workspace**
picks (or initializes) a project folder; **⇆ Connect remote…** adds a server-side
one (see below). The set persists between runs. When you launch from the app menu
(cwd is `$HOME`, so no project is auto-detected) just add your folder once. You
can also target one directly: `priorstates gui --project /path`.

**Launch bar.** Above the tabs is a one-click row to start work in the selected
workspace, in two groups:

- **Launch agent** — **Claude**, **Codex**, **Gemini** (each opens in a terminal
  **already `cd`-ed into the workspace**, so the nearest `.priorstates/` resolves and
  the agent starts with that project's memory + journal live) and **Antigravity**
  (opens the IDE on the folder). A `⚠` means that agent's PriorStates MCP server
  isn't wired yet — run **Agents → install** so it can see PriorStates's tools.
- **Open in** — **VSCode** (and Cursor / Windsurf / VSCode Insiders if present),
  opened on the workspace folder. These are editors, not MCP clients, so no `⚠`;
  the PriorStates tools come from whichever agent extension you run inside them.

Only tools found on your `PATH` show a button (on macOS, installed `.app`s count
too). For a **remote** workspace, terminal agents launch over `ssh -t` on the
server (narrowed to CLIs actually present there), while editors open it with
VSCode-style `--remote ssh-remote+host` from your local machine.

### Remote: research env on a server (VSCode-style)

When the **research environment** lives on a remote server (the data, the
embedding model, and the code your mdlab blocks run), use **`priorstates connect`** —
it works like VSCode Remote-SSH: the engine runs on the server, only the UI comes
back to your desktop.

```bash
priorstates connect server ~/research        # ssh in, run PriorStates there, open it locally
priorstates connect server ~/research --port 7900
```

It SSHes to `server`, launches the cockpit **on the server** (with writes +
mdlab-run enabled), forwards a free local port, and opens it in your browser.
Everything — memory/journal, embedding, and **running mdlab code blocks** —
executes on the server in its real environment; your desktop just renders.
Press **▶ Run** on an `.mdlab.md` doc to execute its blocks on the server.

**Auto-bootstrap (like VSCode Remote-SSH).** If PriorStates isn't on the server,
`connect` **ships it there automatically** (to `~/.priorstates-app/`) and runs from
that copy — you don't have to install it on each host. The server only needs
`python3` and `numpy` (auto-installed if missing) -- the cockpit is pure Python too,
plus SSH access. `--install` re-ships an updated copy. SSH auth (password /
passphrase / host-key) is handled in the terminal window the GUI opens.

In the **GUI**, click **Connect remote…** and enter `host:/project/path`
(e.g. `ai2:~/research`) — or just the host to use the server's default project.
The local **Open Cockpit** (your local workspace) and a remote **Connect** use
separate ports, so they don't interfere.

**Add a launcher** (so PriorStates shows in your application menu / on the desktop):

```bash
priorstates install-launcher            # app-menu entry + icon
priorstates install-launcher --desktop  # also drop an icon on your Desktop
priorstates install-launcher --uninstall
```

(The `.deb`/`.pkg` packages add a launcher automatically; this command is for
pip/pipx installs. It works regardless of PATH — the entry runs
`python3 -m priorstates gui` with an absolute interpreter.)

## 9. CLI reference

```text
priorstates init [PATH] [--global-only] [--download-model]

priorstates memory add NAME --type T [--description D] [--body B] [--scope project|global] [--pin] [--overwrite]
priorstates memory search QUERY [-k N] [--type T] [--scope all|global|project]
priorstates memory list [--scope ...]
priorstates memory pin NAME [--unpin] [--scope ...]
priorstates memory delete NAME [--scope ...]
priorstates memory reindex [--scope ...]

priorstates journal add --topic T --outcome O --title TI [--body B] [--tag X ...] [--evidence E ...] [--supersedes ID]
priorstates journal search [--topic T] [--outcome O] [--tag X] [--since D] [--until D] [--query Q] [-k N]
priorstates journal regen

priorstates mdlab run FILE [FILE ...]

priorstates agents install [AGENT ...] [--no-protocol]
priorstates agents uninstall [AGENT ...]
priorstates agents status
priorstates agents protocol [AGENT ...] [--off]

priorstates cockpit [--port P] [--host H] [--project PATH] [--allow-open] [--allow-write]
priorstates connect HOST [REMOTE_PROJECT] [--port P] [--remote-port R]   # run on a server, open locally
priorstates gui [--project PATH]
priorstates mcp                      # run the MCP server (agents launch this)
priorstates doctor                   # config + embedder backend + agent status
priorstates install-launcher [--desktop] [--uninstall]           # desktop/app-menu entry
```

`--body`/`--body` omitted? `add` reads the body from stdin. Any command also
works as `python3 -m priorstates …`.

## 10. Data locations, Git, backup

```
~/.priorstates/                 global config + memory + model
  config.toml                model, agents, outcomes, backup
  memory/*.md                global memories
  memory.psmem                derived index

<project>/.priorstates/         project scope
  memory/*.md  memory.psmem
  journal/INDEX.md  entries/  by_topic/  digests/
  journal.psmem
```

All plain Markdown — `grep` it, edit it, delete a `.psmem` and it rebuilds.

**Git:** commit the journal (durable shared history), ignore the indexes:

```gitignore
# <project>/.gitignore
.priorstates/*.psmem
.priorstates/journal/*.psmem
# optional: keep memory local
# .priorstates/memory/
```

`git add .priorstates/journal` to share findings with your team. Optional backup to
a remote is configured under `[backup]` in `config.toml`.

## 11. Troubleshooting

- **`priorstates: command not found`** — use `python3 -m priorstates …`, or add the
  user scripts dir to PATH (`export PATH="$HOME/.local/bin:$PATH"`).
- **`Building wheel for UNKNOWN` / nothing installed** — your build tooling is
  too old for `pyproject.toml` metadata. Fix:
  `pip uninstall -y UNKNOWN && pip install --user --upgrade pip setuptools wheel && pip install --user --force-reinstall .`
- **`embedder: hashing` in `doctor`** — no semantic model installed (lexical
  fallback in use). Run `priorstates init --download-model`.
- **Agent doesn't see the tools** — `priorstates agents status`; re-run
  `priorstates agents install`; restart the agent. The MCP server needs the `mcp`
  package (`pip install --user mcp`).
- **Agent isn't journaling** — confirm the protocol block is present
  (`priorstates agents protocol`), and that the agent was opened in a folder you
  ran `priorstates init` in.
- **GUI won't open** — install Tk (`sudo apt install python3-tk`; on macOS
  `brew install python-tk` or use python.org's Python).
- **Cockpit won't start** — it's pure Python; check the terminal output for the error.

Uninstall: `priorstates agents uninstall`, then remove the package
(`sudo apt remove priorstates` / `brew uninstall priorstates`) or the pip install.
Your `.priorstates/` data is left untouched.
