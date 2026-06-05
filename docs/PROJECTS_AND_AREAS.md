# Projects & Areas — the two axes of "where your memory comes from"

PriorStates scopes memory along **two independent axes**. Getting them straight
is the whole mental model:

- **Project** — *where* you're working: a code repo / folder (or a remote host).
  Carries **project-scoped** memory + journal in `<project>/.priorstates/` —
  facts true for *this codebase*. In the desktop GUI, projects are the **left
  sidebar**; on the CLI, the project is auto-detected from your current
  directory.
- **Area** — *what hat* you're wearing: `core-dev`, `model-research`, `strategy`,
  `ops`, `audit`, … Carries a **named global pack** in
  `~/.priorstates/areas/<area>/` — facts true for *this kind of work*, across all
  projects. Selected with `--area NAME` (CLI) or the **Area dropdown** (GUI).

> There's also a third thing that used to share the name "workspace": a
> **`.pspack` pack**, which is a *portable export* of memory + journal you
> publish/import to share knowledge. That's an artifact, not a place or a lens —
> see [the cockpit/share docs](USER_GUIDE.md#8-the-cockpit-web-and-the-desktop-gui).

## They compose

What an agent recalls is always **Project memory + active Area pack**, unioned:

```
        AREA  →   core-dev    model-research   strategy     ops        audit
PROJECT ↓      ┌────────────┬───────────────┬───────────┬───────────┬───────────┐
  bts-repo     │ build/arch │ feature ideas │ live params│ deploys  │ cert trail │
  research-repo│        (+ each project's own .priorstates memory, always)        │
  ny4-box (⇆)  └────────────┴───────────────┴───────────┴───────────┴───────────┘
```

Pick a **row** (which Project) and a **column** (which Area); recall is that cell.
You switch **Projects often** (per task/repo) and **Areas rarely** (per role /
session). A person mostly lives in one Area; they hop Projects all day.

## In the desktop GUI

```
┌─────────────────────────────────────────────────────────────┐
│ 🔭 PriorStates        Area: [ strategy ▾ ]      [Update][Docs]│ ← Area = global mode (header)
├───────────────┬─────────────────────────────────────────────┤
│ PROJECTS      │   bts-repo                                    │
│ ▸ bts-repo  ● │   Launch:  Claude  Codex  Gemini   VS Code …  │ ← agents/cockpit launched
│ ▸ research    │   Cockpit ▸                                   │   here inherit the Area
│ ⇆ ny4-box     │                                               │
│ + Add project │                                               │
└───────────────┴─────────────────────────────────────────────┘
```

- The **left sidebar** is your list of **Projects** (local folders + remote
  hosts). Add, select, or connect to them as before.
- The **Area dropdown** in the header is a single global selector — you're in
  exactly one Area at a time. Changing it re-scopes recall for *every* project at
  once. Type a new name into it to **create** an Area on the fly.
- Whatever you launch next — an **agent CLI** or the **web cockpit** — inherits
  the selected Area (via `$PRIORSTATES_AREA`), so it recalls from that Area's
  pack. Switching Area also re-renders your pinned context for the new Area.

## Usage scenarios

**A. Strategy quant, normal day.** Opens the app → Area is already `strategy`
(remembered from last session) → clicks the `bts-repo` project → launches Claude.
The agent recalls **strategy params (area) + bts-repo notes (project)**. No
thought about scopes — they picked "where" once and "which hat" stays put.

**B. Same person switches to a gateway bug.** Flips the Area dropdown to
`core-dev`. *Same project*, but the agent now recalls build/architecture
invariants instead of live trading params — no folder change, no re-clone.

**C. Cross-area handoff (the promotion gate).** In `model-research`, a result is
validated. They tag it and publish only that subset:

```bash
priorstates --area model-research memory tag "model M v3" promoted
priorstates --area model-research pack publish --tag promoted --sign
```

The strategy teammate installs it into their area — provisional research never
leaks across the boundary:

```bash
priorstates --area strategy pack install <link>
```

**D. Onboarding.** A new hire mounts the team's `core-dev` area pack once and
their agent immediately knows the architecture + the dozen documented dead ends —
no month of tribal knowledge.

## On the CLI

```bash
priorstates --area strategy memory add "M v3 live on 5A" --type project --scope global --tag promoted
priorstates --area core-dev  memory search "gateway checksum"   # only core-dev recall
priorstates areas                                               # list areas + the active one
priorstates --area strategy cockpit                             # cockpit mounted on the strategy area
```

`--area` (or `$PRIORSTATES_AREA`) selects the area for that invocation; the model
cache and your signing identity stay **shared** on the root home, so areas are
cheap (no per-area model re-download).

## Rules of thumb

- **Project = location, Area = lens.** Don't encode "what kind of work" into
  folders; that's what Areas are for.
- **Keep Areas few and stable** (the 5 above cover most desks). Many tiny areas
  hurt more than they help.
- **Cross areas on purpose**, never by ambient access — use the promotion gate
  (`export/publish --tag`) so only validated knowledge crosses, with provenance.
- **Pinned context follows the Area** — switching Area re-renders the pinned
  block your agents see, so each hat brings its own standing rules.

See also: [USER_GUIDE.md](USER_GUIDE.md) · the trust model (signed packs +
import scan) in the cockpit/share docs.
