"""Memory write path: create / delete / pin ``.md`` files.

Ported from the reference writer; the valid ``type`` set now comes from the
active config rather than a fixed enum.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import time
from datetime import datetime
from pathlib import Path

SLUG_RE = re.compile(r"[^a-z0-9]+")


class MemoryWriteError(Exception):
    pass


def assign_claim_id(name: str, created_ns: int) -> str:
    """A stable, immutable claim id derived from name + creation time.

    Deterministic so backfill is idempotent: the same (name, created_ns) always
    yields the same id. Renaming the *file* never changes it; edges (a later phase)
    reference this id, not the slug. See the trust-graph data spec.
    """
    h = hashlib.sha256(f"{name}\0{created_ns}".encode("utf-8")).digest()
    return "cl_" + base64.b32encode(h).decode("ascii").lower().rstrip("=")[:12]


def _today() -> str:
    return datetime.now().date().isoformat()


def make_slug(name: str, max_len: int = 80) -> str:
    s = SLUG_RE.sub("-", name.lower()).strip("-") or "memory"
    return s[:max_len].rstrip("-") if len(s) > max_len else s


def _frontmatter_value(path: Path, key: str) -> str | None:
    """Read a single top-level frontmatter value (ignores indented metadata lines)."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace").split("---\n", 2)
    except OSError:
        return None
    if len(head) < 3:
        return None
    for line in head[1].splitlines():
        if line.startswith(key + ":") and not line.startswith((" ", "\t")):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def _frontmatter_name(path: Path) -> str | None:
    return _frontmatter_value(path, "name")


def find_existing_by_name(memory_dir: Path, name: str) -> Path | None:
    name_norm = name.strip()
    for p in memory_dir.glob("*.md"):
        if p.name in ("MEMORY.md", "INDEX.md", "README.md"):
            continue
        if _frontmatter_name(p) == name_norm:
            return p
    return None


def _norm_tags(tags) -> list[str]:
    """De-dup + order-preserve a list of tag strings (lowercased, trimmed)."""
    out: list[str] = []
    for t in tags or []:
        t = str(t).strip().lower()
        if t and t not in out:
            out.append(t)
    return out


def build_frontmatter(*, name: str, type_str: str, description: str, pinned: bool,
                      valid_types: list[str], tags: list[str] | None = None,
                      id: str | None = None, as_of: str | None = None,
                      valid_until: str | None = None, confidence: float | None = None,
                      source: str | None = None, evidence: list[str] | None = None) -> str:
    if type_str not in valid_types:
        raise MemoryWriteError(f"unknown type {type_str!r}; valid: {valid_types}")
    lines = [f"name: {name}", f"description: {description}", f"type: {type_str}"]
    # trust-graph claim fields (all optional; absence = sensible defaults on read)
    if id:
        lines.append(f"id: {id}")
    if as_of:
        lines.append(f"as_of: {as_of}")
    if valid_until:
        lines.append(f"valid_until: {valid_until}")
    if confidence is not None:
        lines.append(f"confidence: {confidence:g}")
    if source:
        lines.append(f"source: {source}")
    if pinned:
        lines.append("pinned: true")
    tags = _norm_tags(tags)
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    ev = [e.strip() for e in (evidence or []) if e and str(e).strip()]
    if ev:
        lines.append(f"evidence: [{', '.join(ev)}]")
    return "\n".join(lines) + "\n"


def create_memory(*, name: str, type_str: str, description: str, body: str,
                  memory_dir: Path, valid_types: list[str],
                  pinned: bool = False, overwrite: bool = False,
                  tags: list[str] | None = None,
                  as_of: str | None = None, valid_until: str | None = None,
                  confidence: float | None = None, source: str | None = None,
                  evidence: list[str] | None = None) -> Path:
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)
    name = name.strip()
    if not name:
        raise MemoryWriteError("name must be non-empty")
    body = body.strip()
    if not body:
        raise MemoryWriteError("body must be non-empty")

    existing = find_existing_by_name(memory_dir, name)
    if existing is not None and not overwrite:
        raise MemoryWriteError(f"a memory named {name!r} already exists at {existing}; "
                               f"pass overwrite=True to replace it")

    # Stable claim id: reuse the existing one on overwrite (keeps any edges intact),
    # else derive one from name + creation time. as_of/source default sensibly.
    claim_id = _frontmatter_value(existing, "id") if (existing is not None and overwrite) else None
    if not claim_id:
        claim_id = assign_claim_id(name, time.time_ns())
    if as_of is None:
        as_of = _today()
    # NOTE: do NOT default source to "local" — authored memories leave it absent
    # (absence == locally authored). Baking "source: local" would block pack import
    # from stamping its provenance (`source: <pack>`), since the stamp won't overwrite
    # an existing key. "local" is applied as the read-time default instead.

    fm = build_frontmatter(name=name, type_str=type_str, description=description.strip(),
                           pinned=pinned, valid_types=valid_types, tags=tags,
                           id=claim_id, as_of=as_of, valid_until=valid_until,
                           confidence=confidence, source=source, evidence=evidence)
    content = f"---\n{fm}---\n{body}\n"
    path = memory_dir / f"{make_slug(name)}.md"
    if path.exists() and (existing is None or existing != path):
        h = hashlib.sha256(f"{name}:{time.time()}".encode()).hexdigest()[:6]
        path = memory_dir / f"{make_slug(name)}-{h}.md"
    if existing is not None and overwrite:
        path = existing
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path


def ensure_claim_fields(path: Path) -> bool:
    """Backfill ``id`` + ``as_of`` on a pre-trust-graph memory file, in place.

    Idempotent: a file that already has both top-level keys is left untouched. All
    existing frontmatter (incl. an indented ``metadata:`` block) and the body are
    preserved — new keys are appended to the frontmatter. Returns True if changed.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return False  # no frontmatter — not a claim file we manage
    fm_lines = parts[1].splitlines()
    top_keys: set[str] = set()
    name = path.stem
    for ln in fm_lines:
        if ln and not ln.startswith((" ", "\t")) and ":" in ln:
            k = ln.split(":", 1)[0].strip()
            top_keys.add(k)
            if k == "name":
                name = ln.split(":", 1)[1].strip().strip('"').strip("'")
    add: list[str] = []
    st = path.stat()
    if "id" not in top_keys:
        created_ns = getattr(st, "st_ctime_ns", None) or int(st.st_ctime * 1e9)
        add.append(f"id: {assign_claim_id(name, created_ns)}")
    if "as_of" not in top_keys:
        add.append(f"as_of: {datetime.fromtimestamp(st.st_mtime).date().isoformat()}")
    if not add:
        return False
    new_text = f"{parts[0]}---\n" + "\n".join(fm_lines + add) + f"\n---\n{parts[2]}"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def delete_memory(name: str, *, memory_dir: Path) -> Path | None:
    existing = find_existing_by_name(Path(memory_dir), name)
    if existing is None:
        return None
    existing.unlink()
    return existing


def set_pinned(name: str, pinned: bool, *, memory_dir: Path) -> Path | None:
    existing = find_existing_by_name(Path(memory_dir), name)
    if existing is None:
        return None
    parts = existing.read_text(encoding="utf-8").split("---\n", 2)
    if len(parts) < 3:
        raise MemoryWriteError(f"{existing} has no frontmatter")
    new_lines, saw = [], False
    for line in parts[1].splitlines():
        if line.strip().startswith("pinned:"):
            saw = True
            if pinned:
                new_lines.append("pinned: true")
        else:
            new_lines.append(line)
    if pinned and not saw:
        new_lines.append("pinned: true")
    new_text = f"---\n{chr(10).join(new_lines)}\n---\n{parts[2]}"
    tmp = existing.with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, existing)
    return existing


# --- graph edges ----------------------------------------------------------- #
EDGE_MIRROR = {
    "supersedes": "superseded_by", "superseded_by": "supersedes",
    "contradicts": "contradicts", "corroborates": "corroborates", "relates": "relates",
}


def _split_md(path: Path):
    parts = Path(path).read_text(encoding="utf-8").split("---\n", 2)
    if len(parts) < 3:
        raise MemoryWriteError(f"{path} has no frontmatter")
    return parts                                            # [pre, fm_text, body]


def _write_md(path: Path, parts, fm_lines: list[str]) -> None:
    new_text = f"{parts[0]}---\n" + "\n".join(fm_lines) + f"\n---\n{parts[2]}"
    tmp = Path(path).with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, Path(path))


def _edit_list_key(path: Path, key: str, *, add: str | None = None, remove: str | None = None) -> None:
    """Add/remove a value in an inline-list frontmatter key (`key: [a, b]`), in place.
    Splits on commas only (edge refs / evidence contain ':' and '/')."""
    parts = _split_md(path)
    out, cur, idx = [], [], None
    for line in parts[1].splitlines():
        if line.startswith(key + ":") and not line.startswith((" ", "\t")):
            v = line.split(":", 1)[1].strip()
            if v.startswith("[") and v.endswith("]"):
                v = v[1:-1]
            cur = [p.strip().strip("\"'") for p in v.split(",") if p.strip()]
            idx = len(out)
            out.append(None)
        else:
            out.append(line)
    if add and add not in cur:
        cur.append(add)
    if remove:
        cur = [c for c in cur if c != remove]
    new_line = f"{key}: [{', '.join(cur)}]" if cur else None
    if idx is not None:
        out.pop(idx) if new_line is None else out.__setitem__(idx, new_line)
    elif new_line is not None:
        out.append(new_line)
    _write_md(path, parts, out)


def _set_scalar_key(path: Path, key: str, value: str) -> None:
    parts = _split_md(path)
    out, saw = [], False
    for line in parts[1].splitlines():
        if line.startswith(key + ":") and not line.startswith((" ", "\t")):
            saw = True
            out.append(f"{key}: {value}")
        else:
            out.append(line)
    if not saw:
        out.append(f"{key}: {value}")
    _write_md(path, parts, out)


def add_edge(name: str, kind: str, target: str, *, memory_dir: Path,
             condition: str | None = None, remove: bool = False):
    """Add (or remove) a graph edge between two claims, writing the mirror edge on
    the other side too. `target` may be a claim name or a claim id. Returns
    ``(src_path, target_path|None)`` or ``None`` if the source/target can't be found.
    """
    if kind not in EDGE_MIRROR:
        raise MemoryWriteError(f"unknown edge kind {kind!r}; valid: {sorted(EDGE_MIRROR)}")
    memory_dir = Path(memory_dir)
    src = find_existing_by_name(memory_dir, name)
    if src is None:
        return None
    tpath = find_existing_by_name(memory_dir, target)
    # ensure both have ids (so edges reference the stable id, not the slug)
    ensure_claim_fields(src)
    if tpath:
        ensure_claim_fields(tpath)
    src_id = _frontmatter_value(src, "id")
    target_id = _frontmatter_value(tpath, "id") if tpath else (target if target.startswith("cl_") else None)
    if not target_id:
        return None
    mirror = EDGE_MIRROR[kind]
    _edit_list_key(src, kind, **({"remove": target_id} if remove else {"add": target_id}))
    if tpath and src_id:
        _edit_list_key(tpath, mirror, **({"remove": src_id} if remove else {"add": src_id}))
    if condition and not remove:
        _set_scalar_key(src, "condition", f'"{condition}"')
        if tpath:
            _set_scalar_key(tpath, "condition", f'"{condition}"')
    return (str(src), str(tpath) if tpath else None)


def parse_tags(value: str | None) -> list[str]:
    """Parse a frontmatter ``tags:`` value into a list.

    Tolerant of ``[a, b]``, ``a, b`` and ``a b`` forms (the inline-list, CSV and
    whitespace conventions that show up across hand-written and generated files).
    """
    if not value:
        return []
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    parts = re.split(r"[,\s]+", v)
    return _norm_tags(p.strip().strip("\"'") for p in parts if p.strip())


def add_tags(name: str, tags: list[str], *, memory_dir: Path,
             remove: bool = False) -> tuple[Path, list[str]] | None:
    """Merge (or, with ``remove``, drop) ``tags`` on an existing memory.

    Returns ``(path, resulting_tags)`` or ``None`` if no memory matches ``name``.
    Idempotent: adding a tag already present is a no-op.
    """
    existing = find_existing_by_name(Path(memory_dir), name)
    if existing is None:
        return None
    parts = existing.read_text(encoding="utf-8").split("---\n", 2)
    if len(parts) < 3:
        raise MemoryWriteError(f"{existing} has no frontmatter")
    fm_lines, cur, saw_i = [], [], None
    for i, line in enumerate(parts[1].splitlines()):
        if line.strip().startswith("tags:"):
            cur = parse_tags(line.split(":", 1)[1])
            saw_i = len(fm_lines)
            fm_lines.append(None)  # placeholder, filled below
        else:
            fm_lines.append(line)
    want = _norm_tags(tags)
    if remove:
        result = [t for t in cur if t not in want]
    else:
        result = _norm_tags(cur + want)
    tag_line = f"tags: [{', '.join(result)}]" if result else None
    if saw_i is not None:
        if tag_line is None:
            fm_lines.pop(saw_i)
        else:
            fm_lines[saw_i] = tag_line
    elif tag_line is not None:
        fm_lines.append(tag_line)
    new_text = f"---\n{chr(10).join(fm_lines)}\n---\n{parts[2]}"
    tmp = existing.with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, existing)
    return existing, result
