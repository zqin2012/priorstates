"""Share a pack (memory + journal) as a portable `.pspack` bundle.

Phase 0 of the "share pack" experiment: export the markdown that makes up a
pack into a single tar.gz, and import someone else's bundle into your local
store. The `.psmem` indexes are derived, so a bundle is just text files + a
manifest; importing writes the files and reindexes, after which the memories
surface through the existing MCP tools — no new agent wiring.

Trust (the moat, even at v0): import verifies per-file checksums, shows a summary
and asks for confirmation before ingesting, stamps each imported item with its
provenance (`source:` / `imported:`), and never auto-pins imported memory.
"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FORMAT = "pack/1"
_RESERVED = {"MEMORY.md", "INDEX.md", "README.md"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_md(text: str):
    """('frontmatter', 'body') for a `---\\n…\\n---\\n…` file; ('', text) if none."""
    if not text.startswith("---\n"):
        return "", text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2]


def _fm_get(fm: str, key: str) -> str | None:
    for ln in fm.splitlines():
        if ln.startswith(key + ":"):
            return ln.split(":", 1)[1].strip()
    return None


def _fm_inject(text: str, extra: dict) -> str:
    """Add `key: value` lines to a file's frontmatter (idempotent-ish)."""
    fm, body = _split_md(text)
    if not fm:
        return text
    add = "".join(f"{k}: {v}\n" for k, v in extra.items() if f"{k}:" not in fm)
    return "---\n" + fm + add + "---\n" + body


def _fm_rename(text: str, new_name: str) -> str:
    fm, body = _split_md(text)
    lines = fm.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("name:"):
            lines[i] = f"name: {new_name}"
            break
    return "---\n" + "\n".join(lines) + "\n---\n" + body


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def _fm_tags(text: str) -> set[str]:
    """Tags declared in a file's frontmatter (memory or journal), as a set."""
    from ..memory.writer import parse_tags
    return set(parse_tags(_fm_get(_split_md(text)[0], "tags")))


def export_pack(config, *, scope: str = "project", out_path=None,
                     name: str | None = None, author: str | None = None,
                     tags: list[str] | None = None,
                     types: list[str] | None = None, sign: bool = False) -> Path:
    """Bundle a pack's memory + journal into a `.pspack`.

    `tags` / `types` are an optional **selection filter** — the promotion gate.
    When `tags` is given, only memory/journal items carrying at least one of
    those tags are exported; when `types` is given, only memories of those types.
    This is how a desk exports "only the validated facts" (`--tag promoted`)
    across an area boundary instead of leaking the whole provisional store.
    """
    want_tags = {t.strip().lower() for t in (tags or []) if t.strip()}
    want_types = {t.strip().lower() for t in (types or []) if t.strip()}

    mem_dirs = []
    if scope in ("project", "all") and config.memory_project_dir and Path(config.memory_project_dir).exists():
        mem_dirs.append(Path(config.memory_project_dir))
    if scope in ("global", "user", "all") or (scope == "project" and not mem_dirs):
        if Path(config.memory_global_dir).exists():
            mem_dirs.append(Path(config.memory_global_dir))

    memory, journal, members = [], [], {}
    seen = set()
    skipped_mem = skipped_jr = 0
    for d in mem_dirs:
        for p in sorted(d.glob("*.md")):
            if p.name in _RESERVED or p.name in seen:
                continue
            seen.add(p.name)
            text = p.read_text(encoding="utf-8", errors="replace")
            if want_tags and not (_fm_tags(text) & want_tags):
                skipped_mem += 1
                continue
            if want_types and (_fm_get(_split_md(text)[0], "type") or "note").strip().lower() not in want_types:
                skipped_mem += 1
                continue
            raw = p.read_bytes()
            arc = "memory/" + p.name
            members[arc] = raw
            memory.append({"file": arc, "name": _fm_get(text, "name") or p.stem,
                           "sha256": _sha(raw)})

    jd = config.journal_dir
    if scope in ("project", "all") and jd and (Path(jd) / "entries").exists():
        for p in sorted((Path(jd) / "entries").glob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            # type filter is memory-only; a journal entry has no `type`, so a
            # types-only selection excludes journal entirely.
            if want_types and not want_tags:
                skipped_jr += 1
                continue
            if want_tags and not (_fm_tags(text) & want_tags):
                skipped_jr += 1
                continue
            raw = p.read_bytes()
            arc = "journal/" + p.name
            members[arc] = raw
            journal.append({"file": arc, "id": p.stem, "sha256": _sha(raw)})

    ws_name = name or (Path(config.project_root).name if config.project_root else "pack")
    manifest = {
        "format": FORMAT, "name": ws_name, "author": author or "anonymous",
        "created_utc": _now(), "priorstates_version": _pkg_version(),
        "memory": memory, "journal": journal,
    }
    if want_tags or want_types:
        manifest["selection"] = {
            "tags": sorted(want_tags), "types": sorted(want_types),
            "skipped_memory": skipped_mem, "skipped_journal": skipped_jr,
        }
    if sign:
        from . import identity
        sig = identity.sign_manifest(config, manifest)
        if sig is None:
            raise RuntimeError("cannot sign: install the `sign` extra "
                               "(pip install 'priorstates[sign]') for ed25519 support")
        manifest["signature"] = sig
    out = Path(out_path) if out_path else Path.cwd() / (ws_name.replace("/", "-") + ".pspack")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add(tar, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
        for arc, raw in members.items():
            _add(tar, arc, raw)
    out.write_bytes(buf.getvalue())
    return out


def _add(tar: tarfile.TarFile, name: str, data: bytes):
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))


def _pkg_version() -> str:
    try:
        from importlib.metadata import version
        return version("priorstates")
    except Exception:
        return "0.1.0"


# --------------------------------------------------------------------------- #
# import
# --------------------------------------------------------------------------- #
def read_bundle(src) -> tuple[dict, dict]:
    """Return (manifest, {arcname: bytes}) from a file path, URL, or bytes."""
    if isinstance(src, (bytes, bytearray)):
        data = bytes(src)
    elif str(src).startswith(("http://", "https://")):
        import os
        req = urllib.request.Request(str(src))
        key = os.environ.get("PRIORSTATES_HUB_KEY")
        if key:  # access-controlled internal hub gates reads on this header
            req.add_header("X-PriorStates-Key", key)
        from . import plugins
        for h, v in plugins.registry().hub_headers(str(src)).items():  # SSO/EE auth
            req.add_header(h, v)
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (user-provided URL)
            data = r.read()
    else:
        data = Path(src).read_bytes()
    members, manifest = {}, {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            b = tar.extractfile(m).read()
            if m.name == "manifest.json":
                manifest = json.loads(b.decode("utf-8"))
            else:
                members[m.name] = b
    if manifest.get("format") != FORMAT:
        raise ValueError("not a recognized .pspack bundle")
    return manifest, members


def summarize(manifest: dict) -> str:
    s = ("pack '%s' by %s — %d memor%s, %d journal entr%s (created %s)"
         % (manifest.get("name", "?"), manifest.get("author", "anonymous"),
            len(manifest.get("memory", [])), "y" if len(manifest.get("memory", [])) == 1 else "ies",
            len(manifest.get("journal", [])), "y" if len(manifest.get("journal", [])) == 1 else "ies",
            manifest.get("created_utc", "?")))
    sel = manifest.get("selection")
    if sel and (sel.get("tags") or sel.get("types")):
        crit = []
        if sel.get("tags"):
            crit.append("tags=" + ",".join(sel["tags"]))
        if sel.get("types"):
            crit.append("types=" + ",".join(sel["types"]))
        s += ("  [filtered export: %s; %d memor%s + %d journal skipped]"
              % (" ".join(crit), sel.get("skipped_memory", 0),
                 "y" if sel.get("skipped_memory", 0) == 1 else "ies",
                 sel.get("skipped_journal", 0)))
    from . import identity
    status, who = identity.verify_manifest(manifest)
    s += {"unsigned": "  · ⚠ UNSIGNED",
          "valid": f"  · ✓ signed by {who}",
          "invalid": f"  · ✗ SIGNATURE INVALID ({who}) — do NOT trust",
          "unverified": f"  · signed by {who} (unverified — install the `sign` extra)"}[status]
    return s


def import_pack(config, src, *, verify: bool = True) -> dict:
    """Write a bundle's memory + journal into the local store and reindex.

    Caller is responsible for any confirmation; this just performs the import.
    """
    from ..memory import writer
    manifest, members = read_bundle(src)
    label = "%s by %s" % (manifest.get("name", "shared"), manifest.get("author", "anonymous"))
    stamp = {"source": label, "imported": _now()}

    if verify:
        for item in manifest.get("memory", []) + manifest.get("journal", []):
            b = members.get(item["file"])
            if b is None or _sha(b) != item.get("sha256"):
                raise ValueError(f"checksum/content mismatch for {item['file']}")

    # memory → project dir if present, else global
    mem_dir = Path(config.memory_project_dir) if config.memory_project_dir else Path(config.memory_global_dir)
    mem_dir.mkdir(parents=True, exist_ok=True)
    mem_added, mem_renamed = 0, 0
    for item in manifest.get("memory", []):
        raw = members[item["file"]].decode("utf-8", "replace")
        name = _fm_get(_split_md(raw)[0], "name") or item.get("name") or "memory"
        if writer.find_existing_by_name(mem_dir, name) is not None:
            name = name + " (imported)"
            raw = _fm_rename(raw, name)
            mem_renamed += 1
        raw = _fm_inject(raw, stamp)
        slug = writer.make_slug(name)
        dest = mem_dir / f"{slug}.md"
        i = 2
        while dest.exists():
            dest = mem_dir / f"{slug}-{i}.md"; i += 1
        dest.write_text(raw, encoding="utf-8")
        mem_added += 1

    # journal → project entries (preserve original id/date); requires a project
    jr_added, jr_skipped = 0, 0
    jd = config.journal_dir
    if manifest.get("journal"):
        if jd:
            edir = Path(jd) / "entries"; edir.mkdir(parents=True, exist_ok=True)
            for item in manifest["journal"]:
                dest = edir / Path(item["file"]).name
                if dest.exists():
                    jr_skipped += 1; continue
                dest.write_text(_fm_inject(members[item["file"]].decode("utf-8", "replace"), stamp),
                                encoding="utf-8")
                jr_added += 1
        else:
            jr_skipped = len(manifest["journal"])

    # rebuild derived indexes
    from ..memory import api as mem
    mem.reindex(config, "all")
    mem.render_pinned(config)
    if jr_added and jd:
        from . import journal as J
        J.regenerate_all(config)

    return {"name": manifest.get("name"), "memory_added": mem_added, "memory_renamed": mem_renamed,
            "journal_added": jr_added, "journal_skipped": jr_skipped,
            "journal_needs_project": bool(manifest.get("journal") and not jd)}


def packaged_demo() -> Path:
    """Path to the bundled demo workspace shipped with the package."""
    return Path(__file__).resolve().parents[1] / "data" / "demo.pspack"


_demo_label_cache = None


def demo_label() -> str:
    """The provenance `source:` label that import_pack stamps for the demo."""
    global _demo_label_cache
    if _demo_label_cache is None:
        m, _ = read_bundle(packaged_demo())
        _demo_label_cache = "%s by %s" % (m.get("name", "priorstates-demo"), m.get("author", "PriorStates"))
    return _demo_label_cache


def _memory_files(config):
    dirs = []
    if config.memory_project_dir and Path(config.memory_project_dir).exists():
        dirs.append(Path(config.memory_project_dir))
    if Path(config.memory_global_dir).exists():
        dirs.append(Path(config.memory_global_dir))
    for d in dirs:
        for p in d.glob("*.md"):
            if p.name not in _RESERVED:
                yield p


def _journal_files(config):
    jd = config.journal_dir
    if jd and (Path(jd) / "entries").exists():
        yield from (Path(jd) / "entries").glob("*.md")


def _source_of(p: Path) -> str | None:
    try:
        return _fm_get(_split_md(p.read_text(encoding="utf-8", errors="replace"))[0], "source")
    except OSError:
        return None


def has_source(config, label: str) -> bool:
    """True if any memory/journal item was imported with this provenance label."""
    return any(_source_of(p) == label for p in _memory_files(config)) or \
        any(_source_of(p) == label for p in _journal_files(config))


def remove_source(config, label: str) -> dict:
    """Delete every memory/journal item imported with `label`; reindex + regenerate."""
    n = j = 0
    for p in list(_memory_files(config)):
        if _source_of(p) == label:
            p.unlink(); n += 1
    for p in list(_journal_files(config)):
        if _source_of(p) == label:
            p.unlink(); j += 1
    from ..memory import api as mem
    mem.reindex(config, "all"); mem.render_pinned(config)
    if j and config.journal_dir:
        from . import journal as J
        J.regenerate_all(config)
    return {"memory_removed": n, "journal_removed": j}
