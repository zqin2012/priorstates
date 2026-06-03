"""High-level memory operations used by the CLI, MCP server, and GUI.

Each write re-indexes the affected scope's ``.psmem`` and re-renders the pinned
block into the configured agent context files.
"""
from __future__ import annotations

from pathlib import Path

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
               pinned: bool = False, scope: str = "project", overwrite: bool = False) -> dict:
    if scope == "project" and not config.memory_project_dir:
        scope = "global"
    mem_dir, _ = _scope_dir_and_bin(config, scope)
    path = writer.create_memory(name=name, type_str=type_str, description=description,
                                body=body, memory_dir=mem_dir,
                                valid_types=config.memory_types, pinned=pinned, overwrite=overwrite)
    reindex(config, scope)
    render_pinned(config)
    return {"path": str(path), "scope": scope}


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
                  scope: str = "all") -> list[dict]:
    bins = _bins_for_scope(config, scope)
    if not bins:
        return []
    emb = get_embedder(config)
    qv = emb.embed_one(query)
    hits = []
    for bp in bins:
        with MemoryStore(bp) as st:
            for h in st.search(qv, k=k, type_filter=type_str):
                hits.append({"name": h.name, "description": h.description, "body": h.body,
                             "type": h.type, "score": round(h.score, 4), "pinned": h.pinned,
                             "src": h.src_path})
    hits.sort(key=lambda r: r["score"], reverse=True)
    return hits[:k]


def get_memory(config, name: str, scope: str = "all") -> dict | None:
    for bp in _bins_for_scope(config, scope):
        with MemoryStore(bp) as st:
            h = st.get_by_name(name)
            if h:
                return {"name": h.name, "description": h.description, "body": h.body,
                        "type": h.type, "pinned": h.pinned, "src": h.src_path}
    return None


def list_pinned(config, scope: str = "all") -> list[dict]:
    out = []
    for bp in _bins_for_scope(config, scope):
        with MemoryStore(bp) as st:
            for h in st.list_pinned():
                out.append({"name": h.name, "description": h.description,
                            "type": h.type, "src": h.src_path})
    return out
