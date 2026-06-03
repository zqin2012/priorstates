# PriorStates — Data Model Reference

Byte-level and schema reference for the on-disk formats. The Markdown files are the source of
truth; the `.psmem` binary is a rebuildable derived index.

---

## 1. `.psmem` binary index (frozen v1)

Carried over from the proven `.cmem` format. All integers little-endian; each
section starts on a 4096-byte page boundary so the kernel can map pages lazily.

```
offset 0           ┌────────────────────────────┐
                   │ Header (128 bytes)         │
embed_offset  ───▶ ├────────────────────────────┤
                   │ Embeddings N × dim × f16   │   row i = L2-normalized vec for entry i
index_offset  ───▶ ├────────────────────────────┤
                   │ IndexEntry × N (64 B each) │
strings_offset ──▶ ├────────────────────────────┤
                   │ Strings blob (name/desc/   │   referenced by (off,len); not NUL-terminated
                   │ src_path, packed UTF-8)    │
bodies_offset ───▶ ├────────────────────────────┤
                   │ Bodies blob (packed UTF-8) │
                   └────────────────────────────┘
```

### Header (128 bytes)

| Off | Type | Field | Notes |
|--:|---|---|---|
| 0 | char[4] | `magic` | `"PMEM"` |
| 4 | u16 | `version` | `1` |
| 6 | u16 | `flags` | bit0: embeddings L2-normalized (always 1) |
| 8 | u32 | `n_entries` | memory/journal record count |
| 12 | u32 | `dim` | embedding dim (384 for bge-small) |
| 16 | u32 | `embed_dtype` | 1=float16, 2=float32 |
| 20 | u32 | `reserved0` | — |
| 24 | u64 | `embed_offset` | → embeddings |
| 32 | u64 | `index_offset` | → IndexEntry array |
| 40 | u64 | `strings_offset` | → strings blob |
| 48 | u64 | `strings_len` | strings byte length |
| 56 | u64 | `bodies_offset` | → bodies blob |
| 64 | u64 | `bodies_len` | bodies byte length |
| 72 | u64 | `created_unix_ns` | build timestamp |
| 80 | u8[48] | `reserved` | zeroed |

### IndexEntry (64 bytes × N)

| Off | Type | Field | Notes |
|--:|---|---|---|
| 0 | u32 | `name_off` | → strings |
| 4 | u32 | `name_len` | |
| 8 | u32 | `desc_off` | → strings |
| 12 | u32 | `desc_len` | |
| 16 | u32 | `body_off` | → bodies |
| 20 | u32 | `body_len` | |
| 24 | u32 | `src_path_off` | → strings |
| 28 | u32 | `src_path_len` | |
| 32 | u8 | `type_code` | see type codes |
| 33 | u8[3] | `pad` | |
| 36 | f32 | `ctime_unix` | source ctime |
| 40 | f32 | `mtime_unix` | source mtime |
| 44 | u32 | `flags` | bit0 `FLAG_PINNED` |
| 48 | u8[16] | `name_hash` | SHA-256(name)[:16], dedup |

### Type codes

Core (stable): `other=0, user=1, preference=2, project=3, reference=4, note=5`.
Plugin-defined types are assigned codes ≥ 64 at registration so they never
collide with the core range. (The original reserved 5-9 for trading auto-ingest
sources; those move into plugins under the ≥64 range.)

### Invariants

- Embeddings are L2-normalized → dot-product equals cosine similarity.
- Atomic rebuild: write `<file>.tmp`, then `os.rename()` over the target.
- Readers `stat()` the file each query; on inode/mtime change they re-`mmap`. No
  process restart needed after a rebuild.
- The whole file is reconstructable from the Markdown sources; deleting it is
  safe (next index rebuilds it).

---

## 2. Memory entry frontmatter

| Field | Req | Type | Notes |
|---|:--:|---|---|
| `name` | ✓ | string | unique slug; derives filename via `[^a-z0-9]+ → -`, ≤80 chars, 6-char hash on collision |
| `description` | ✓ | string | one line; **embedded** for recall (keep it meaningful) |
| `type` | ✓ | enum | `user · preference · project · reference · note` (+ plugin types) |
| `pinned` |   | bool | default false; true → injected into every agent's context file |
| `links` |   | list | `[[other-name]]` cross-references |
| `metadata` |   | map | free-form (origin session, etc.) |

Body: free Markdown. For `preference`/`project` the convention is a `**Why:**`
and `**How to apply:**` line, as in the reference system.

Files live in `~/.priorstates/memory/` (global) or `<workspace>/.priorstates/memory/`
(project). A search may union both (`scope='all'`).

---

## 3. Journal entry frontmatter

| Field | Req | Type | Notes |
|---|:--:|---|---|
| `id` | ✓ (auto) | string | `YYYYMMDD_<topic>_<bodyhash6>`; stable across re-saves if body unchanged |
| `date` | ✓ (auto) | ISO date | workspace-local day |
| `topic` | ✓ | string | grouping key (label configurable; was `strategy`) |
| `outcome` | ✓ | enum | from `journal.outcomes` config; default set below |
| `title` | ✓ | string | one-line headline; INDEX anchor text |
| `tldr` |   | string | else auto-extracted from `**TL;DR**:` or first paragraph, ≤250 chars |
| `tags` |   | list | free-text |
| `evidence` |   | list | paths / URLs / PR refs; rendered as links |
| `supersedes` |   | string | prior entry id; sets `superseded_by` on that entry |
| `superseded_by` |   | string | auto-added on the superseded entry |
| `links` |   | list | cross-refs to memories/entries |
| `doc`, `body_hash`, `commit_*` |   | string | auto-added (source doc, body hash, captured commit SHAs) |

### Default outcome vocabulary (most-actionable-first)

`winner · decision · gotcha · bug · loser · inconclusive · note`

| outcome | meaning |
|---|---|
| `winner` | change/config that improved the target metric |
| `decision` | a non-obvious choice + rationale (architectural/scaffolding) |
| `gotcha` | a workflow/data pitfall worth recording |
| `bug` | a defect in code or data |
| `loser` | a config that hurt, or a falsified hypothesis |
| `inconclusive` | tested, no clear signal |
| `note` | durable note that isn't a result |

Unknown outcomes save with a warning and normalize to `inconclusive` in
generated digests.

---

## 4. `INDEX.md` entry line (regex)

Parser (cockpit + journal engine) matches, between
`<!-- priorstates:journal-index-start -->` and `<!-- priorstates:journal-index-end -->`:

```
^- (\d{4}-\d{2}-\d{2}) \[([^\]]+)\]\s*((?:\[[^\]]*\]\s*)*)\*\*([^*]+)\*\*:\s*\[([^\]]+)\]\(([^)]+)\)(?:\s+[—-]\s+(.*))?$
   │  date              │ outcome     │ optional [superseded → id] │ topic     │ title       │ path     │ tldr
```

Content outside the markers is hand-owned and never rewritten.

---

## 5. Derived journal views

`priorstates journal regen` (or an mdlab `​```journal` run) rebuilds:

- `INDEX.md` — chronological, newest first, between the markers.
- `by_topic/<topic>.md` — one page per topic: a "by outcome" section
  (outcome-ordered) and a reverse-chronological timeline.
- `by_topic/README.md` — topics sorted by entry count, with last-entry date.
- `digests/<YYYY-MM>.md` — monthly "issue": entries grouped by topic then
  outcome, with TL;DRs.
- `digests/README.md` — month table with counts.

All regeneration is idempotent (overwrites in place); entry files in `entries/`
are the source of truth for these views, just as the `.psmem` is for search.
