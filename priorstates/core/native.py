"""Bridge other agents' built-in ("native") memory into the shared store.

Hosts like Claude Code keep their own private memory. A fact saved there is
invisible to the user's other tools — which defeats the point of a shared store.
This module (a) detects populated native memory so `doctor` can warn, and
(b) imports it into PriorStates so every agent sees the same memory.

One-shot and idempotent: re-importing skips memories that already exist (match by
name) unless `overwrite` is set. A continuous watcher could build on this later.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .indexer import _parse_frontmatter

# Host native memory type -> PriorStates memory type.
_TYPE_MAP = {
    "user": "user", "preference": "preference", "feedback": "preference",
    "project": "project", "reference": "reference", "note": "note",
}


def _claude_project_slug(path: Path) -> str:
    # Claude Code names a project's memory dir by its absolute path with the path
    # separators replaced by '-' (e.g. /home/u/app -> -home-u-app).
    return str(path).replace(os.sep, "-")


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "memory"


def _count(d: Path) -> int:
    if not d.is_dir():
        return 0
    return sum(1 for p in d.glob("*.md") if p.name != "MEMORY.md")


def native_sources(cfg) -> list[dict]:
    """Host native-memory dirs that exist AND hold memories. Each entry:
    {agent, scope, dir, count}. Currently knows Claude Code's global store and
    the current project's store."""
    home = Path.home()
    candidates: list[tuple[str, str, Path]] = [
        ("claude", "global", home / ".claude" / "memory"),
    ]
    if cfg.project_root:
        candidates.append((
            "claude", "project",
            home / ".claude" / "projects"
            / _claude_project_slug(Path(cfg.project_root)) / "memory",
        ))
    out = []
    for agent, scope, d in candidates:
        n = _count(d)
        if n:
            out.append({"agent": agent, "scope": scope, "dir": d, "count": n})
    return out


def import_native(cfg, *, scope_override: str | None = None,
                  overwrite: bool = False, dry_run: bool = False) -> dict:
    """Import every native memory into the shared store. Returns a summary dict
    with imported / skipped / errors (lists of names) and the sources scanned."""
    from ..memory import api as mem

    imported: list[str] = []
    skipped: list[str] = []
    errors: list[tuple[str, str]] = []
    sources = native_sources(cfg)

    for src in sources:
        scope = scope_override or src["scope"]
        for p in sorted(src["dir"].glob("*.md")):
            if p.name == "MEMORY.md":
                continue
            try:
                fm, body = _parse_frontmatter(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                errors.append((p.name, str(e)))
                continue
            name = _slugify(fm.get("name") or p.stem)
            ptype = _TYPE_MAP.get((fm.get("type") or "note").lower(), "note")
            desc = fm.get("description", "")
            if not overwrite and mem.show_memory(cfg, name, scope=scope):
                skipped.append(name)
                continue
            if dry_run:
                imported.append(name)
                continue
            try:
                mem.add_memory(cfg, name=name, type_str=ptype, description=desc,
                               body=(body or "").strip(), scope=scope,
                               overwrite=overwrite, source=f"native:{src['agent']}")
                imported.append(name)
            except Exception as e:  # noqa: BLE001
                errors.append((name, str(e)))

    return {
        "imported": imported, "skipped": skipped, "errors": errors,
        "sources": [{"agent": s["agent"], "scope": s["scope"],
                     "dir": str(s["dir"]), "count": s["count"]} for s in sources],
    }
