"""Render the pinned-memory block into agent context files.

Generalized from the reference (which wrote only ~/.claude/CLAUDE.md): the same
marker-delimited block is written into every configured agent's context file,
preserving everything outside the markers.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core.store import MemoryStore

BEGIN = "<!-- BEGIN priorstates: pinned (auto-generated, do not edit) -->"
END = "<!-- END priorstates: pinned -->"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)


def render_pinned_block(bin_paths: list[Path]) -> tuple[str, int]:
    """Build the block from one or more ``.psmem`` files (global + project)."""
    pinned = []
    seen = set()
    for bp in bin_paths:
        if not bp or not Path(bp).exists():
            continue
        with MemoryStore(bp) as store:
            for h in store.list_pinned(with_body=True):
                if h.name in seen:
                    continue
                seen.add(h.name)
                pinned.append(h)
    lines = [BEGIN, "# Pinned memories", ""]
    if not pinned:
        lines.append("_(no pinned memories — set `pinned: true` on any memory to add one)_")
    else:
        lines.append(f"These {len(pinned)} memories are flagged always-relevant. "
                     f"Treat them as standing user preferences / hard rules.")
        lines.append("")
        for h in pinned:
            lines.append(f"## {h.name}")
            if h.description:
                lines.append(f"_{h.description}_")
            lines += ["", h.body, ""]
    lines.append(END)
    return "\n".join(lines) + "\n", len(pinned)


def write_marked_block(target: Path, block: str, begin: str, end: str) -> str:
    """Insert/replace a marker-delimited block in a file, preserving the rest."""
    target = Path(target)
    block_re = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(block, encoding="utf-8")
        return "created"
    cur = target.read_text(encoding="utf-8")
    if begin in cur and end in cur:
        new = block_re.sub(block.rstrip("\n"), cur, count=1)
        if new == cur:
            return "unchanged"
        target.write_text(new, encoding="utf-8")
        return "updated"
    sep = "" if cur.endswith("\n") else "\n"
    target.write_text(cur + sep + "\n" + block, encoding="utf-8")
    return "appended"


def remove_marked_block(target: Path, begin: str, end: str) -> bool:
    target = Path(target)
    if not target.exists():
        return False
    cur = target.read_text(encoding="utf-8")
    if begin not in cur:
        return False
    block_re = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    new = block_re.sub("", cur).rstrip("\n") + "\n"
    target.write_text(new, encoding="utf-8")
    return True


def write_block(target: Path, block: str) -> str:
    return write_marked_block(target, block, BEGIN, END)


def remove_block(target: Path) -> bool:
    return remove_marked_block(target, BEGIN, END)
