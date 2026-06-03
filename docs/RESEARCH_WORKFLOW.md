# Research workflow — where folders go & how agents journal

Two practical questions answered: **where do I create research folders**, and
**how do the agents actually add journal entries**.

---

## 1. Where research folders go

PriorStates has two scopes:

| Scope | Location | Holds | Created by |
|---|---|---|---|
| **global** | `~/.priorstates/` | identity + cross-project preferences; the embedding model | `priorstates init` (once) |
| **project** | `<dir>/.priorstates/` | this project's **memory** *and* its **journal** | `priorstates init` run **inside `<dir>`** |

A "research folder" is simply **any directory you run `priorstates init` in**. That
creates:

```
<your-folder>/.priorstates/
  memory/            project memories (facts/decisions about this work)
  journal/
    INDEX.md         chronological index (newest first)
    entries/*.md     one file per finding
    by_topic/  digests/   generated views
  config.toml        optional per-project overrides
```

How scope is resolved: PriorStates (and the MCP server an agent launches) walks
**up from the current directory** to the nearest ancestor containing
`.priorstates/`. So the journal an agent reads/writes is the one for **the
workspace the agent was opened in**.

### Recommended layouts

- **Per repo (default).** Run `priorstates init` at each repo root you want a
  journal for. Findings track that codebase. When you open the repo in Claude
  Code / Codex / Gemini, its journal is used automatically.
  ```bash
  cd ~/code/my-app && priorstates init
  ```

- **A dedicated research workspace.** One folder, many experiment sub-folders,
  one shared journal — good for cross-cutting research not tied to a single
  repo. Put mdlab notes and data wherever you like underneath it.
  ```bash
  mkdir -p ~/research && cd ~/research && priorstates init
  ~/research/
    .priorstates/journal/        ← the shared journal
    auth-experiments/*.mdlab.md
    ranking-models/*.mdlab.md
  ```

- **Global memory only.** If you just want portable preferences across all
  agents and no per-project journal, skip `init` in a project; `~/.priorstates`
  alone is enough for memory.

> The `topic` field is what groups journal entries *within* a project — use it
> for the experiment/area (e.g. `auth-refactor`, `ranking-v2`). You don't need a
> separate folder per topic.

### Git: commit the journal, ignore the index

The journal is durable shared history — commit it. The `.psmem` binaries are
derived and rebuildable — ignore them. Memory is more personal — your call.

```gitignore
# in <project>/.gitignore
.priorstates/*.psmem
.priorstates/journal/*.psmem
# optional: keep memory local
# .priorstates/memory/
```

Then `git add .priorstates/journal` to share findings with your team.

---

## 2. How agents add journal entries

There are three ways entries get written; you'll use all three.

### a) The agent records them itself (the main path)

After `priorstates agents install`, each agent has the MCP tools `journal_search`,
`journal_add`, `journal_regen` (plus the `memory_*` tools) **and** a standing
instruction — the **research-protocol block** PriorStates writes into the agent's
context file (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`). That block tells the
agent to:

1. `journal_search` **before** non-trivial work (don't repeat a known loser /
   contradict a recorded decision),
2. `journal_add` **when it reaches a durable conclusion**, and
3. `memory_add` when it learns a durable preference/fact.

So once wired, agents journal on their own as they work. You can manage the
instruction independently of MCP:

```bash
priorstates agents install            # writes MCP + pinned + protocol (default)
priorstates agents install --no-protocol   # wire tools but don't add the instruction
priorstates agents protocol           # (re)write just the protocol block
priorstates agents protocol --off     # remove just the protocol block
```

The block lives between `<!-- BEGIN priorstates: protocol --> … <!-- END … -->`
markers; **anything you write elsewhere in the file is preserved**, so add your
own house rules around it.

### b) You ask, in-session

Even without the standing instruction, just tell the agent:

> "Record that in the PriorStates journal — topic `auth-refactor`, outcome
> `winner`."

and it calls `journal_add`. Or "what does the journal say about X?" →
`journal_search`.

### c) Manually — CLI or mdlab

For your own notes, or scripted runs:

```bash
priorstates journal add --topic auth-refactor --outcome winner \
  --title "httpOnly cookies cut XSS" \
  --body "**TL;DR**: moved the session token to an httpOnly+SameSite cookie; p95 unchanged." \
  --tag security --evidence PR#412

priorstates journal search --topic auth-refactor
priorstates journal regen          # rebuild INDEX.md + by_topic/ + digests/
```

Or inside a `*.mdlab.md` doc, a fenced `journal` block becomes an entry when you
run the file:

~~~markdown
```journal
---
topic: auth-refactor
outcome: winner
title: httpOnly cookies cut XSS
tags: [security]
---
**TL;DR**: moved the token to an httpOnly+SameSite cookie; p95 unchanged.
```
~~~
```bash
priorstates mdlab run notes.mdlab.md
```

### The entry schema (what to put)

| field | required | notes |
|---|:--:|---|
| `topic` | ✓ | stable kebab-case area, e.g. `auth-refactor` |
| `outcome` | ✓ | `winner · decision · gotcha · bug · loser · inconclusive · note` |
| `title` | ✓ | one line |
| `body` | ✓ | start with `**TL;DR**:` and the headline result/number |
| `tags`, `evidence`, `supersedes` | – | optional; `supersedes` = a prior entry id, which auto-marks it superseded |

---

## Putting it together (a session)

```text
You open ~/code/my-app in Claude Code (you ran `priorstates init` there once,
and `priorstates agents install`).

Agent, before changing auth:   journal_search(topic="auth-refactor")
  → sees a prior [loser]: "localStorage token w/ CSP only".
Agent does the work, concludes, then:
  journal_add(topic="auth-refactor", outcome="winner",
              title="httpOnly cookies cut XSS",
              body="**TL;DR**: ... p95 unchanged", evidence=["PR#412"])
You later open the cockpit:      priorstates cockpit
  → the finding is in the Journal tab, grouped under auth-refactor.
```

See also: [QUICKSTART.md](QUICKSTART.md).
