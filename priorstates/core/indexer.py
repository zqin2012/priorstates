"""Markdown → ``.psmem`` indexer.

Reads memory ``.md`` files (YAML-ish frontmatter), embeds name+description+body,
and writes a single binary via atomic rename. Ported from the reference indexer;
generalized to (a) take the embedder's ``dim`` rather than hardcoding 384,
(b) accept multiple source dirs, and (c) ingest journal entries as a source.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .format import (
    DTYPE_F16, DTYPE_F32, ENTRY_SIZE, FLAG_CONTRADICTED, FLAG_EMBED_NORMALIZED,
    FLAG_FLAGGED, FLAG_HAS_EDGES, FLAG_PINNED, FLAG_STALE, FLAG_SUPERSEDED,
    HEADER_SIZE, Header, IndexEntry, TYPE_CODES, align_up,
)

EDGE_KINDS = ("supersedes", "superseded_by", "contradicts", "corroborates", "relates")

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
SKIP_NAMES = {"MEMORY.md", "INDEX.md", "README.md"}


@dataclass(slots=True)
class MemoryRecord:
    name: str
    description: str
    type_code: int
    body: str
    src_path: str
    ctime_unix: float
    mtime_unix: float
    pinned: bool = False
    # trust-graph scalars (v2 index); confidence is never 0 unless explicitly set
    confidence: float = 1.0
    as_of_unix: float = 0.0
    superseded: bool = False
    contradicted: bool = False
    stale: bool = False
    flagged: bool = False
    has_edges: bool = False


def _parse_list(v: str | None) -> list[str]:
    """Parse an inline frontmatter list like ``[journal:x, run:y]`` → ['journal:x','run:y'].
    Splits on commas only (refs contain ':' and '/')."""
    if not v:
        return []
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [p.strip().strip("\"'") for p in v.split(",") if p.strip()]


def _date_to_unix(s: str | None) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len("YYYY-MM-DDTHH:MM:SS")] if "T" in s else s, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def compute_confidence(*, source: str | None, signer: str | None, scan: str | None,
                       evidence: list[str], corroborates_n: int = 0,
                       explicit=None, trust_cfg: dict | None = None) -> float:
    """Reference confidence formula (Phase 1 — no outcome ledger yet, that's Phase 3).
    Pure + explainable; weights overridable via the ``[trust]`` config."""
    if explicit is not None and str(explicit).strip() != "":
        try:
            return max(0.0, min(1.0, float(explicit)))
        except (TypeError, ValueError):
            pass
    cfg = trust_cfg or {}
    src = (source or "").strip().lower()
    imported = bool(src) and src != "local"
    if (scan or "").strip().lower() == "flagged":
        base = float(cfg.get("base_flagged", 0.10))
    elif imported:
        base = float(cfg.get("base_signed", 0.60)) if signer else float(cfg.get("base_unsigned", 0.40))
    else:
        base = float(cfg.get("base_local", 0.60))
    ev = [e for e in (evidence or []) if e]
    bonus = 0.10 if ev else 0.0
    if any(str(e).split(":", 1)[0] in ("run", "commit", "data") for e in ev):
        bonus += 0.10                                   # grounded in a verifiable artifact
    corr = min(0.20, 0.05 * max(0, corroborates_n))
    return max(0.0, min(1.0, base + bonus + corr))


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_text, rest = m.group(1), text[m.end():]
    fm: dict[str, str] = {}
    in_metadata = False
    for line in fm_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.rstrip() == "metadata:":
            in_metadata = True
            continue
        if in_metadata and line.startswith("  ") and ":" in line:
            k, _, v = line.strip().partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
            continue
        if ":" in line:
            in_metadata = False
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, rest


def _read_memory(path: Path) -> MemoryRecord | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    fm, body = _parse_frontmatter(text)
    name = (fm.get("name") or path.stem).strip()
    type_str = (fm.get("type") or "note").lower()
    type_code = TYPE_CODES.get(type_str, TYPE_CODES["note"])
    pinned = (fm.get("pinned") or "").strip().lower() in ("true", "yes", "1", "on")
    st = path.stat()
    # trust-graph fields (all optional; sensible defaults keep recall identical when absent)
    as_of_unix = _date_to_unix(fm.get("as_of")) or float(st.st_mtime)
    valid_until_unix = _date_to_unix(fm.get("valid_until"))
    scan = (fm.get("scan") or "").strip().lower()
    evidence = _parse_list(fm.get("evidence"))
    confidence = compute_confidence(
        source=fm.get("source"), signer=fm.get("signer"), scan=scan,
        evidence=evidence, corroborates_n=len(_parse_list(fm.get("corroborates"))),
        explicit=fm.get("confidence"))
    return MemoryRecord(
        name=name, description=fm.get("description", "").strip(),
        type_code=type_code, body=body.strip(), src_path=str(path),
        ctime_unix=float(st.st_ctime), mtime_unix=float(st.st_mtime), pinned=pinned,
        confidence=confidence, as_of_unix=as_of_unix,
        superseded=bool(_parse_list(fm.get("superseded_by"))),
        contradicted=bool(_parse_list(fm.get("contradicts"))),
        stale=bool(valid_until_unix) and valid_until_unix < time.time(),
        flagged=(scan == "flagged"),
        has_edges=any(_parse_list(fm.get(k)) for k in EDGE_KINDS),
    )


def scan_memory_dirs(dirs: list[Path]) -> list[MemoryRecord]:
    out: list[MemoryRecord] = []
    seen: set[str] = set()
    for d in dirs:
        if not d or not Path(d).exists():
            continue
        for p in sorted(Path(d).glob("*.md")):
            if p.name in SKIP_NAMES:
                continue
            rec = _read_memory(p)
            if rec is None or not rec.body:
                continue
            if rec.name in seen:  # project shadows global on name collision
                continue
            seen.add(rec.name)
            out.append(rec)
    return out


def scan_journal_entries(journal_dir: Path) -> list[MemoryRecord]:
    """Ingest journal entries as searchable records (type 'journal')."""
    edir = Path(journal_dir) / "entries"
    out: list[MemoryRecord] = []
    if not edir.exists():
        return out
    for p in sorted(edir.glob("*.md")):
        rec = _read_memory(p)
        if rec is None or not rec.body:
            continue
        rec.type_code = TYPE_CODES["journal"]
        out.append(rec)
    return out


def _embedding_text(rec: MemoryRecord) -> str:
    return "\n".join(p for p in (rec.name, rec.description, rec.body) if p)


def _intern(strings: bytearray, value: str) -> tuple[int, int]:
    data = value.encode("utf-8")
    off = len(strings)
    strings.extend(data)
    return off, len(data)


def build_binary(records: list[MemoryRecord], embeddings: np.ndarray, out_path: Path,
                 *, dtype: int = DTYPE_F16, dim: int = 384) -> dict:
    n = len(records)
    if n == 0:
        raise ValueError("no records to index")
    if embeddings.shape != (n, dim):
        raise ValueError(f"embeddings shape {embeddings.shape} != ({n}, {dim})")
    emb_bytes = (embeddings.astype(np.float16) if dtype == DTYPE_F16
                 else embeddings.astype(np.float32)).tobytes()

    strings = bytearray()
    bodies = bytearray()
    entries: list[IndexEntry] = []
    for rec in records:
        name_off, name_len = _intern(strings, rec.name)
        desc_off, desc_len = _intern(strings, rec.description)
        src_off, src_len = _intern(strings, rec.src_path)
        body_off = len(bodies)
        body_bytes = rec.body.encode("utf-8")
        bodies.extend(body_bytes)
        flags = (FLAG_PINNED if rec.pinned else 0)
        if rec.superseded:
            flags |= FLAG_SUPERSEDED
        if rec.contradicted:
            flags |= FLAG_CONTRADICTED
        if rec.stale:
            flags |= FLAG_STALE
        if rec.flagged:
            flags |= FLAG_FLAGGED
        if rec.has_edges:
            flags |= FLAG_HAS_EDGES
        entries.append(IndexEntry(
            name_off=name_off, name_len=name_len, desc_off=desc_off, desc_len=desc_len,
            body_off=body_off, body_len=len(body_bytes), src_path_off=src_off, src_path_len=src_len,
            type_code=rec.type_code, ctime_unix=rec.ctime_unix, mtime_unix=rec.mtime_unix,
            confidence=float(rec.confidence), as_of_unix=float(rec.as_of_unix), flags=flags,
            name_hash=hashlib.sha256(rec.name.encode("utf-8")).digest()[:16],
        ))

    embed_offset = align_up(HEADER_SIZE)
    index_offset = align_up(embed_offset + len(emb_bytes))
    strings_offset = align_up(index_offset + n * ENTRY_SIZE)
    bodies_offset = align_up(strings_offset + len(strings))
    total_size = bodies_offset + len(bodies)

    header = Header(flags=FLAG_EMBED_NORMALIZED, n_entries=n, dim=dim, embed_dtype=dtype,
                    embed_offset=embed_offset, index_offset=index_offset,
                    strings_offset=strings_offset, strings_len=len(strings),
                    bodies_offset=bodies_offset, bodies_len=len(bodies),
                    created_unix_ns=time.time_ns())

    buf = bytearray(total_size)
    buf[:HEADER_SIZE] = header.pack()
    buf[embed_offset:embed_offset + len(emb_bytes)] = emb_bytes
    pos = index_offset
    for e in entries:
        buf[pos:pos + ENTRY_SIZE] = e.pack()
        pos += ENTRY_SIZE
    buf[strings_offset:strings_offset + len(strings)] = strings
    buf[bodies_offset:bodies_offset + len(bodies)] = bodies

    out_path = Path(out_path)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "wb") as f:
        f.write(buf)
        f.flush()
        os.fsync(f.fileno())
    # os.replace atomically overwrites an existing destination on BOTH Windows and
    # POSIX; os.rename raises FileExistsError on Windows when out_path exists
    # (breaks every reindex/import after the first on Windows).
    os.replace(tmp, out_path)
    return {"n_entries": n, "total_bytes": total_size, "out_path": str(out_path)}


def index_records(records: list[MemoryRecord], out_path: Path, embedder, *,
                  dtype: int = DTYPE_F16, verbose: bool = False) -> dict:
    if not records:
        raise RuntimeError("no records to index")
    texts = [_embedding_text(r) for r in records]
    t0 = time.time()
    emb = embedder.embed(texts)
    if verbose:
        print(f"[indexer] embedded {len(texts)} via {getattr(embedder,'backend','?')} "
              f"in {time.time()-t0:.2f}s")
    return build_binary(records, emb, out_path, dtype=dtype, dim=embedder.dim)
