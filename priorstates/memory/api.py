"""High-level memory operations used by the CLI, MCP server, and GUI.

Each write re-indexes the affected scope's ``.psmem`` and re-renders the pinned
block into the configured agent context files.
"""
from __future__ import annotations

from pathlib import Path

from ..core import format as _fmt
from ..core import indexer
from ..core.embedder import get_embedder
from ..core.format import DTYPE_F16, DTYPE_F32
from ..core.store import MemoryStore
from . import pinned as pinned_mod
from . import writer


def _dtype(config) -> int:
    return DTYPE_F32 if config.embed_dtype == "float32" else DTYPE_F16


def _scope_dir_and_bin(config, scope: str) -> tuple[Path, Path]:
    if scope == "project":
        if not config.memory_project_dir:
            raise writer.MemoryWriteError("no project scope — run `priorstates init` in a project first")
        return config.memory_project_dir, config.project_dir / "memory.psmem"
    return config.memory_global_dir, config.memory_global_bin


def reindex(config, scope: str = "all", *, verbose: bool = False) -> dict:
    """Rebuild the .psmem index for a scope (or both). Returns per-scope stats."""
    emb = get_embedder(config)
    stats = {}
    scopes = ["global", "project"] if scope == "all" else [scope]
    for sc in scopes:
        if sc == "project" and not config.memory_project_dir:
            continue
        mem_dir, bin_path = _scope_dir_and_bin(config, sc)
        # Phase 0: backfill claim id / as_of on any pre-trust-graph files (idempotent).
        for p in Path(mem_dir).glob("*.md"):
            if p.name not in indexer.SKIP_NAMES:
                writer.ensure_claim_fields(p)
        recs = indexer.scan_memory_dirs([mem_dir])
        if not recs:
            # nothing to index; remove a stale binary so search returns empty cleanly
            if Path(bin_path).exists():
                Path(bin_path).unlink()
            stats[sc] = {"n_entries": 0}
            continue
        stats[sc] = indexer.index_records(recs, bin_path, emb, dtype=_dtype(config), verbose=verbose)
    return stats


def render_pinned(config, targets: list[Path] | None = None) -> tuple[str, int]:
    """Render the pinned block into agent context files. Targets default to the
    enabled agents' context files (resolved by the agents adapters)."""
    _ensure_index_current(config, "all")
    bins = [p for p in (config.memory_global_bin,
                        (config.project_dir / "memory.psmem") if config.project_dir else None)
            if p and Path(p).exists()]
    block, n = pinned_mod.render_pinned_block(bins)
    if targets is None:
        try:
            from ..agents.adapters import pinned_targets
            targets = pinned_targets(config)
        except Exception:
            targets = []
    for t in targets:
        pinned_mod.write_block(Path(t), block)
    return block, n


def add_memory(config, *, name: str, type_str: str, description: str, body: str,
               pinned: bool = False, scope: str = "project", overwrite: bool = False,
               tags: list[str] | None = None, as_of: str | None = None,
               valid_until: str | None = None, confidence: float | None = None,
               source: str | None = None, evidence: list[str] | None = None) -> dict:
    if scope == "project" and not config.memory_project_dir:
        scope = "global"
    mem_dir, _ = _scope_dir_and_bin(config, scope)
    path = writer.create_memory(name=name, type_str=type_str, description=description,
                                body=body, memory_dir=mem_dir,
                                valid_types=config.memory_types, pinned=pinned,
                                overwrite=overwrite, tags=tags, as_of=as_of,
                                valid_until=valid_until, confidence=confidence,
                                source=source, evidence=evidence)
    reindex(config, scope)
    render_pinned(config)
    return {"path": str(path), "scope": scope}


def show_memory(config, name: str, scope: str = "all") -> dict | None:
    """Return a claim's full frontmatter + body, read from the `.md` (source of
    truth) — surfaces the trust-graph fields (id, as_of, evidence, edges)."""
    for sc in (["project", "global"] if scope == "all" else [scope]):
        if sc == "project" and not config.memory_project_dir:
            continue
        mem_dir, _ = _scope_dir_and_bin(config, sc)
        path = writer.find_existing_by_name(Path(mem_dir), name)
        if path:
            fm, body = indexer._parse_frontmatter(Path(path).read_text(encoding="utf-8"))
            return {"scope": sc, "path": str(path), "frontmatter": fm, "body": body.strip()}
    return None


def tag_memory(config, name: str, tags: list[str], *, scope: str = "all",
               remove: bool = False) -> dict:
    """Add or remove tags on an existing memory (across the given scope).

    Tags are governance metadata (e.g. ``promoted``, ``reviewed``) that
    `workspace export --tag` filters on — they do not affect semantic recall, so
    no re-index is needed.
    """
    changed, result = [], []
    for sc in (["global", "project"] if scope == "all" else [scope]):
        if sc == "project" and not config.memory_project_dir:
            continue
        mem_dir, _ = _scope_dir_and_bin(config, sc)
        res = writer.add_tags(name, tags, memory_dir=mem_dir, remove=remove)
        if res:
            path, result = res
            changed.append(str(path))
    return {"changed": changed, "tags": result}


def delete_memory(config, name: str, scope: str = "all") -> dict:
    removed = []
    for sc in (["global", "project"] if scope == "all" else [scope]):
        if sc == "project" and not config.memory_project_dir:
            continue
        mem_dir, _ = _scope_dir_and_bin(config, sc)
        p = writer.delete_memory(name, memory_dir=mem_dir)
        if p:
            removed.append(str(p))
            reindex(config, sc)
    render_pinned(config)
    return {"removed": removed}


def pin_memory(config, name: str, pinned: bool = True, scope: str = "all") -> dict:
    changed = []
    for sc in (["global", "project"] if scope == "all" else [scope]):
        if sc == "project" and not config.memory_project_dir:
            continue
        mem_dir, _ = _scope_dir_and_bin(config, sc)
        p = writer.set_pinned(name, pinned, memory_dir=mem_dir)
        if p:
            changed.append(str(p))
            reindex(config, sc)
    render_pinned(config)
    return {"changed": changed, "pinned": pinned}


def _ensure_index_current(config, scope: str) -> None:
    """Rebuild any existing .psmem whose on-disk format version is stale (e.g. a v1
    index after the v2 trust-graph bump) so reads upgrade seamlessly instead of
    crashing. A cheap 6-byte header probe; only rebuilds a valid-but-old index."""
    for sc in (["global", "project"] if scope == "all" else [scope]):
        if sc == "project" and not config.memory_project_dir:
            continue
        try:
            _, bin_path = _scope_dir_and_bin(config, sc)
        except writer.MemoryWriteError:
            continue
        if Path(bin_path).exists():
            v = _fmt.file_version(bin_path)
            if v is not None and v != _fmt.VERSION:
                reindex(config, sc)


def _trust_params(config, *, no_trust: bool = False, min_trust=None,
                  fresh: bool = False) -> tuple[bool, float, float]:
    """(trust_weight, min_trust, halflife_days) from the `[trust]` config + overrides."""
    tcfg = getattr(config, "trust", {}) or {}
    enabled = bool(tcfg.get("enabled", True)) and not no_trust
    mt = float(min_trust) if min_trust is not None else float(tcfg.get("min_trust", 0.0) or 0.0)
    hl = float(tcfg.get("halflife_days", 180.0) or 180.0)
    if fresh:
        hl = max(1.0, hl / 3.0)        # --fresh: weight recency harder (shorter half-life)
    return enabled, mt, hl


def _bins_for_scope(config, scope: str) -> list[Path]:
    out = []
    if scope in ("all", "project") and config.project_dir:
        bp = config.project_dir / "memory.psmem"
        if bp.exists():
            out.append(bp)
    if scope in ("all", "global") and config.memory_global_bin.exists():
        out.append(config.memory_global_bin)
    return out


def search_memory(config, query: str, k: int = 5, type_str: str | None = None,
                  scope: str = "all", *, no_trust: bool = False, min_trust=None,
                  fresh: bool = False) -> list[dict]:
    _ensure_index_current(config, scope)
    bins = _bins_for_scope(config, scope)
    if not bins:
        return []
    tw, mt, hl = _trust_params(config, no_trust=no_trust, min_trust=min_trust, fresh=fresh)
    emb = get_embedder(config)
    qv = emb.embed_one(query)
    n = max(k * 5, 25)                      # wider candidate set so the edge post-rank has context
    hits = []
    for bp in bins:
        with MemoryStore(bp) as st:
            for h in st.search(qv, k=n, type_filter=type_str, trust_weight=tw,
                               min_trust=mt, halflife_days=hl):
                hits.append({"name": h.name, "description": h.description, "body": h.body,
                             "type": h.type, "score": round(h.score, 4), "pinned": h.pinned,
                             "trust": round(h.trust, 4), "fresh": round(h.fresh, 4),
                             "stale": h.stale, "superseded": h.superseded,
                             "contradicted": h.contradicted, "flagged": h.flagged,
                             "has_edges": h.has_edges, "src": h.src_path})
    hits.sort(key=lambda r: r["score"], reverse=True)
    if any(h.get("has_edges") for h in hits):      # only pay the file reads when edges exist
        return _post_rank(hits, k)
    return hits[:k]


def _read_edges(src: str) -> dict:
    try:
        fm, _ = indexer._parse_frontmatter(Path(src).read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {"id": fm.get("id"),
            "superseded_by": indexer._parse_list(fm.get("superseded_by")),
            "contradicts": indexer._parse_list(fm.get("contradicts")),
            "corroborates": indexer._parse_list(fm.get("corroborates"))}


def _post_rank(hits: list[dict], k: int) -> list[dict]:
    """Resolve graph edges over the candidate set: drop claims superseded by a
    present claim, demote+flag the loser of a contradiction, and annotate
    corroboration. See the trust-graph data spec §5."""
    for h in hits:
        ed = _read_edges(h["src"])
        h["_id"] = ed.get("id")
        h["_sb"] = ed.get("superseded_by", [])
        h["_co"] = ed.get("contradicts", [])
        h["_cor"] = ed.get("corroborates", [])
    by_id = {h["_id"]: h for h in hits if h.get("_id")}
    kept = []
    for h in hits:
        if any(t in by_id for t in h["_sb"]):                  # superseded by a present claim → drop
            continue
        rivals = [by_id[t] for t in h["_co"] if t in by_id]
        if any(r["score"] >= h["score"] for r in rivals):      # lost a contradiction → demote + flag
            h["contradicted"] = True
            h["score"] = round(h["score"] * 0.5, 4)
        cor = sum(1 for t in h["_cor"] if t in by_id)
        if cor:
            h["corroboration_count"] = cor
        kept.append(h)
    kept.sort(key=lambda r: r["score"], reverse=True)
    for h in kept:
        for kk in ("_id", "_sb", "_co", "_cor"):
            h.pop(kk, None)
    return kept[:k]


def link_memory(config, name: str, kind: str, target: str, *, scope: str = "all",
                condition: str | None = None, remove: bool = False) -> dict | None:
    """Add/remove a graph edge (and its mirror) between two claims in the same scope."""
    for sc in (["project", "global"] if scope == "all" else [scope]):
        if sc == "project" and not config.memory_project_dir:
            continue
        mem_dir, _ = _scope_dir_and_bin(config, sc)
        res = writer.add_edge(name, kind, target, memory_dir=mem_dir,
                              condition=condition, remove=remove)
        if res:
            reindex(config, sc)        # refresh flags (HAS_EDGES / SUPERSEDED / CONTRADICTED)
            return {"scope": sc, "src": res[0], "target": res[1], "kind": kind, "removed": remove}
    return None


def find_near_dups(config, *, name: str | None = None, text: str | None = None,
                   scope: str = "all", threshold: float | None = None, k: int = 10) -> list[dict]:
    """Candidate near-duplicates of a claim (by name) or free text, by pure cosine.
    Threshold defaults to `[trust].dup_threshold` (0.92)."""
    _ensure_index_current(config, scope)
    thr = float(threshold) if threshold is not None else \
        float((getattr(config, "trust", {}) or {}).get("dup_threshold", 0.92) or 0.92)
    if text is None and name:
        rec = show_memory(config, name, scope=scope)
        if not rec:
            return []
        fm = rec["frontmatter"]
        text = "\n".join(p for p in (fm.get("name", name), fm.get("description", ""),
                                     rec.get("body", "")) if p)
    if not text:
        return []
    emb = get_embedder(config)
    qv = emb.embed_one(text)
    out = []
    for bp in _bins_for_scope(config, scope):
        with MemoryStore(bp) as st:
            for h in st.search(qv, k=k + 1):           # pure cosine; +1 to absorb self
                if name and h.name == name:
                    continue
                if h.score >= thr:
                    out.append({"name": h.name, "score": round(h.score, 4), "src": h.src_path})
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:k]


def get_memory(config, name: str, scope: str = "all") -> dict | None:
    _ensure_index_current(config, scope)
    for bp in _bins_for_scope(config, scope):
        with MemoryStore(bp) as st:
            h = st.get_by_name(name)
            if h:
                return {"name": h.name, "description": h.description, "body": h.body,
                        "type": h.type, "pinned": h.pinned, "src": h.src_path}
    return None


def list_pinned(config, scope: str = "all") -> list[dict]:
    _ensure_index_current(config, scope)
    out = []
    for bp in _bins_for_scope(config, scope):
        with MemoryStore(bp) as st:
            for h in st.list_pinned():
                out.append({"name": h.name, "description": h.description,
                            "type": h.type, "src": h.src_path})
    return out
