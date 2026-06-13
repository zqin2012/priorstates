<div align="center">

# 🔭 PriorStates

### Shared memory &amp; a research journal for your AI agents

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![MCP-native](https://img.shields.io/badge/MCP-native-3fb950.svg)](https://modelcontextprotocol.io/)
[![100% local](https://img.shields.io/badge/100%25-local-3fb950.svg)](#private-by-default)
[![Stars](https://img.shields.io/github/stars/zqin2012/priorstates?style=social)](https://github.com/zqin2012/priorstates)

**Coding agents are amnesiacs** — every session starts cold, re-deriving what you
already taught them and re-running experiments a past session already concluded.
PriorStates gives **Claude, Codex &amp; Gemini** one **local** memory and a searchable
**research journal**, so what one session learns, the next one remembers.

Runs entirely on your machine · CPU-only · no API keys · no cloud calls.

🌐 **[priorstates.com](https://priorstates.com)**  ·  🎬 **[80-second demo](https://priorstates.com)**  ·  📖 **[Docs](docs/USER_GUIDE.md)**

<img src="docs/img/demo.gif" alt="PriorStates in action: save a memory, then recall it by meaning in a brand-new agent session" width="760">

</div>

## Install — in one sentence

Already using Claude, Codex, or Gemini? Hand it one line:

> **Install PriorStates: fetch https://priorstates.com/install.md and follow it.**

The agent reads [`AGENT_INSTALL.md`](AGENT_INSTALL.md), installs the package, wires
itself over MCP, and verifies with `priorstates doctor` — then restart it to load
the new tools.

**Prefer to do it yourself?** Pick your platform:

<details open>
<summary><b>🐧 Linux (Debian / Ubuntu) — the <code>.deb</code> (recommended)</b></summary>

Apt pulls in `python3` + `numpy`, and you get the desktop app, an icon, the
`priorstates` CLI and man pages — nothing else to install:

```bash
curl -fSLO https://priorstates.com/download/priorstates_0.1.14_all.deb
sudo apt install -y ./priorstates_0.1.14_all.deb   # resolves python3 (>= 3.10) + python3-numpy
```

Then just **open “PriorStates” from your application menu** (or run
`priorstates-gui`). The desktop control panel does the rest — initialize your
memory, wire Claude / Codex / Gemini over MCP, and launch the cockpit, all with a
click. No further commands needed. (For agent integration it needs the MCP support
package once — `PIP_BREAK_SYSTEM_PACKAGES=1 pip3 install --user mcp`; the app flags it if it's missing.)

`sudo apt remove priorstates` uninstalls. Re-running the same `apt install`
upgrades in place.

**RHEL / Rocky / Alma / Fedora** — same experience via the `.rpm` (one noarch
package for all of them; on EL9 it pulls `python3.12` automatically):

```bash
curl -fSLO https://priorstates.com/download/priorstates-0.1.14-1.noarch.rpm
sudo dnf install ./priorstates-0.1.14-1.noarch.rpm
```
</details>

<details>
<summary><b>🪟 Windows — the one-click installer (easiest of all)</b></summary>

Download and run
**[PriorStates-Windows-Setup.exe](https://github.com/zqin2012/priorstates/releases/latest/download/PriorStates-Windows-Setup.exe)**
— it auto-installs Python if you don't have it, then installs PriorStates and adds
Start Menu + Desktop shortcuts. Nothing else required.
</details>

<details>
<summary><b>🍎 macOS / any OS with Python 3.10+ — pip</b></summary>

```bash
PIP_BREAK_SYSTEM_PACKAGES=1 pip install --user --no-cache-dir "priorstates @ git+https://github.com/zqin2012/priorstates.git"
priorstates init            # create ~/.priorstates + per-project .priorstates/
priorstates agents install  # wire Claude / Codex / Gemini over MCP
priorstates cockpit         # open the web cockpit → http://127.0.0.1:7700
```

macOS also has a native `.pkg` / Homebrew formula — see
[docs/QUICKSTART.md](docs/QUICKSTART.md).
</details>

Full install matrix (`.deb` / macOS `.pkg` / Windows / source) is in
**[docs/QUICKSTART.md](docs/QUICKSTART.md)**. No model download is required — a
built-in CPU hashing embedder works out of the box.

## What's inside

| | Subsystem | What it does |
|---|---|---|
| 🧠 | **memory** | A local semantic store. Save a fact once — any future session recalls it *by meaning*. Pinned facts are injected into every session. |
| 📓 | **journal** | An append-only research log. Every winner, loser, bug &amp; decision becomes a searchable entry, so no experiment is run twice. |
| 🛰️ | **cockpit** | A **pure-Python** (stdlib-only) local web app that maps your memory, journal &amp; docs — search, group, dashboards. Embedded **terminal** (on by default for a local cockpit; `--no-terminal` to disable) to run your agent CLIs right in the browser. No Node.js, no npm, no build step. |
| 📝 | **mdlab** | Runnable Markdown: interleave prose, code &amp; results in one file and splice output back in. |

All of it is wired into your agents over the open **[MCP](https://modelcontextprotocol.io/)**
protocol by `priorstates agents install` — so they *recall* before acting and
*record* durable conclusions back, automatically.

## MCP server

`priorstates agents install` registers the server into Claude / Codex / Gemini for
you; to run it directly over stdio: **`priorstates mcp`**. It exposes 10 tools:

- **memory** — `memory_add` · `memory_search` · `memory_get` · `memory_list_pinned` · `memory_pin` · `memory_delete`
- **journal** — `journal_add` · `journal_search` · `journal_regen`
- **mdlab** — `mdlab_run`

## See it in action

The **cockpit** maps your whole research surface; the **CLI** captures and recalls from your terminal.

<img src="docs/img/cockpit.png" alt="The PriorStates cockpit — search and manage memory, journal and docs in one local web view" width="820">

<img src="docs/img/cli.png" alt="PriorStates CLI — capture a memory in plain English, list pinned memories, search the journal by outcome" width="720">

## Agent-neutral

One memory store and one journal, surfaced to **Claude Code · Claude Desktop · Codex ·
Gemini · Antigravity** through MCP and a pinned context block — no lock-in, no
rewrites. Switch agents without losing a thing. The **VS Code / JetBrains
extensions** for Claude Code and Codex share their CLI's MCP config, so they're
covered automatically; **Claude Desktop** (its own app) is wired into
`claude_desktop_config.json` too. Every client on the machine reads the *same*
local store, so a memory saved in one is instantly recalled in all the others.

## Private by default

Everything lives under `~/.priorstates/` and per-project `.priorstates/`. The
default embedder is **CPU-only and offline** — no API keys, no telemetry, no cloud
calls. Upgrade to semantic recall with a single optional ~127&nbsp;MB model download
whenever you want.

## Share a pack

Export your memory + journal as a portable bundle and hand it to a teammate (or
host it anywhere — any file or URL works):

```bash
priorstates pack export --name my-project        # → my-project.pspack
priorstates pack import ./my-project.pspack # on the other machine (or a URL)
```

Imported memory surfaces through the same MCP tools — no extra wiring. Imports are
**checksum-verified, shown for confirmation before ingest, and tagged with their
source** (and never auto-pinned). The **cockpit** has **Export** / **Import**
buttons too (Import needs the cockpit started with `--allow-write`).

**New here?** Load a ready-made sample to see PriorStates populated instantly:

```bash
priorstates pack import --demo
```

## Docs

- **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — the everyday-use manual. **Start here.**
- **[docs/PROJECTS_AND_AREAS.md](docs/PROJECTS_AND_AREAS.md)** — Projects vs Areas: the two scoping axes + the GUI Area selector.
- **[docs/QUICKSTART.md](docs/QUICKSTART.md)** — install + first run.
- **[docs/RESEARCH_WORKFLOW.md](docs/RESEARCH_WORKFLOW.md)** — research folders + how agents log to the journal.
- **[docs/DATA_MODEL.md](docs/DATA_MODEL.md)** — on-disk schemas + the `.psmem` layout.
- One-click native installers (the free **Hub edition**) — macOS / Windows / Linux — at **https://priorstates.com/download**.

## Status

**v0.1 — working end-to-end:** memory, journal, mdlab, MCP server (10 tools),
agent wiring (Claude / Codex / Gemini / Antigravity), the web cockpit, and the
desktop launcher are all built and tested. Optional semantic model downloads on
demand; the hashing fallback needs zero setup. A background embedder daemon and
an autonomous `priorstates research` runner are next.

Issues and PRs welcome.

## Get in touch

Questions, ideas, or feedback — **[service@priorstates.com](mailto:service@priorstates.com)**.
Bug reports and feature requests are welcome as GitHub issues.

## License

**Apache-2.0** (permissive + patent grant). See [LICENSE](LICENSE) and [NOTICE](NOTICE).
Copyright 2026 Zhendong Qin.
