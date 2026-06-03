"""Research journal engine.

Ported from the reference mdlab journal runtime and generalized:
  * roots come from :class:`~priorstates.core.config.Config` (no hardcoded paths);
  * the grouping field is ``topic`` (``strategy`` is accepted as an alias);
  * the outcome vocabulary is config-driven;
  * markers are ``priorstates:journal-index-*``;
  * git-commit capture is generic (the project repo + any configured repos);
  * INDEX.md, by_topic/, and digests/ are (re)generated here — no mdlab needed.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_INDEX_START = "<!-- priorstates:journal-index-start -->"
_INDEX_END = "<!-- priorstates:journal-index-end -->"
_FM = "---"
_SAFE_RE = re.compile(r"[^A-Za-z0-9_\-]")
_TLDR_RE = re.compile(r"\*\*TL;DR\*\*\s*:?\s*", re.IGNORECASE)


class JournalError(Exception):
    pass


# --------------------------------------------------------------------------- #
# frontmatter
# --------------------------------------------------------------------------- #
def _parse_frontmatter(text: str) -> dict[str, Any]:
    try:
        import yaml
        loaded = yaml.safe_load(text) or {}
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    out: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\w+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            out[key] = [s.strip().strip("\"'") for s in val[1:-1].split(",") if s.strip()]
        elif val in ("true", "false"):
            out[key] = val == "true"
        elif val.isdigit() or (val.startswith("-") and val[1:].isdigit()):
            out[key] = int(val)
        elif (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            out[key] = val[1:-1]
        else:
            out[key] = val
    return out


def _split_frontmatter_body(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM:
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM:
            end = i
            break
    if end is None:
        return {}, text
    return _parse_frontmatter("\n".join(lines[1:end])), "\n".join(lines[end + 1:]).strip()


# --------------------------------------------------------------------------- #
# paths / helpers
# --------------------------------------------------------------------------- #
def _require_journal_dir(config) -> Path:
    jd = config.journal_dir
    if jd is None:
        raise JournalError(
            "no PriorStates project here — run `priorstates init` in your project root "
            "first (creates ./.priorstates/)."
        )
    (jd / "entries").mkdir(parents=True, exist_ok=True)
    return jd


def _safe_topic(s: str) -> str:
    return _SAFE_RE.sub("_", str(s).strip())[:64] or "unspec"


def _body_hash(body: str, n: int = 6) -> str:
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:n]


def _compute_id(topic: str, date_str: str, body: str) -> str:
    return f"{date_str.replace('-', '')}_{_safe_topic(topic)}_{_body_hash(body)}"


def _git_head(repo: Path) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()[:12] if r.returncode == 0 else None
    except Exception:
        return None


def _commits(config) -> dict[str, str]:
    out: dict[str, str] = {}
    repos: list[Path] = []
    if config.project_root:
        repos.append(config.project_root)
    for r in config.backup_repos:
        repos.append(Path(r).expanduser())
    for p in repos:
        if (p / ".git").exists():
            sha = _git_head(p)
            if sha:
                out[p.name] = sha
    return out


def _extract_tldr(body: str, max_len: int = 250) -> str:
    if not body.strip():
        return ""
    m = _TLDR_RE.search(body)
    if m:
        first = body[m.end():].strip().split("\n\n", 1)[0].strip()
    else:
        first = ""
        for block in body.split("\n\n"):
            s = block.strip()
            if s and not s.startswith("#"):
                first = s
                break
    one = re.sub(r"\s+", " ", first).strip()
    return (one[:max_len - 1].rstrip() + "…") if len(one) > max_len else one


# --------------------------------------------------------------------------- #
# entry model
# --------------------------------------------------------------------------- #
@dataclass
class Entry:
    id: str
    date: str
    topic: str
    outcome: str
    title: str
    tldr: str
    body_hash: str
    doc: str | None
    tags: list[str]
    evidence: list[str]
    supersedes: str | None
    superseded_by: str | None
    commits: dict[str, str]
    body: str
    path: Path
    extras: dict[str, Any] = field(default_factory=dict)


_RESERVED = {"id", "date", "topic", "strategy", "outcome", "title", "tldr",
             "tags", "evidence", "supersedes", "superseded_by", "doc", "body_hash"}


def _entry_to_file(e: Entry) -> str:
    fm = [_FM, f"id: {e.id}", f"date: {e.date}", f"topic: {e.topic}",
          f"outcome: {e.outcome}", f"title: {e.title}"]
    if e.tldr:
        fm.append(f"tldr: {e.tldr}")
    if e.tags:
        fm.append(f"tags: [{', '.join(e.tags)}]")
    if e.evidence:
        fm.append(f"evidence: [{', '.join(e.evidence)}]")
    if e.supersedes:
        fm.append(f"supersedes: {e.supersedes}")
    if e.superseded_by:
        fm.append(f"superseded_by: {e.superseded_by}")
    if e.doc:
        fm.append(f"doc: {e.doc}")
    fm.append(f"body_hash: {e.body_hash}")
    for k, v in e.commits.items():
        fm.append(f"commit_{k}: {v}")
    for k, v in e.extras.items():
        if k in _RESERVED or k.startswith("commit_"):
            continue
        fm.append(f"{k}: {v}")
    fm.append(_FM)
    return "\n".join(fm) + "\n\n" + e.body.rstrip() + "\n"


def _parse_entry_file(path: Path) -> Entry | None:
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return None
    meta, body = _split_frontmatter_body(text)
    if not meta:
        return None
    topic = meta.get("topic") or meta.get("strategy") or ""  # accept alias
    commits = {k[7:]: str(v) for k, v in meta.items() if k.startswith("commit_")}
    extras = {k: v for k, v in meta.items() if k not in _RESERVED and not k.startswith("commit_")}
    return Entry(
        id=str(meta.get("id", path.stem)), date=str(meta.get("date", "")),
        topic=str(topic), outcome=str(meta.get("outcome", "")),
        title=str(meta.get("title", "")), tldr=str(meta.get("tldr", "")) or _extract_tldr(body),
        body_hash=str(meta.get("body_hash", "")),
        doc=str(meta.get("doc")) if meta.get("doc") else None,
        tags=list(meta.get("tags", []) or []), evidence=list(meta.get("evidence", []) or []),
        supersedes=str(meta.get("supersedes")) if meta.get("supersedes") else None,
        superseded_by=str(meta.get("superseded_by")) if meta.get("superseded_by") else None,
        commits=commits, body=body, path=path, extras=extras,
    )


def all_entries(config) -> list[Entry]:
    jd = config.journal_dir
    if jd is None:
        return []
    edir = jd / "entries"
    if not edir.exists():
        return []
    out = [_parse_entry_file(p) for p in sorted(edir.glob("*.md"))]
    return [e for e in out if e is not None]


# --------------------------------------------------------------------------- #
# INDEX + views
# --------------------------------------------------------------------------- #
def _index_line(e: Entry) -> str:
    marker = f"[{e.outcome}]"
    if e.superseded_by:
        marker += f" [superseded → {e.superseded_by}]"
    return f"- {e.date} {marker} **{e.topic}**: [{e.title}](entries/{e.id}.md) — {e.tldr}"


def regenerate_index(config) -> None:
    jd = _require_journal_dir(config)
    entries = sorted(all_entries(config), key=lambda e: e.date, reverse=True)
    body = "\n".join(_index_line(e) for e in entries) or "_No entries yet._"
    idx = jd / "INDEX.md"
    cur = idx.read_text() if idx.exists() else ""
    if _INDEX_START in cur and _INDEX_END in cur:
        before, _, rest = cur.partition(_INDEX_START)
        _, _, after = rest.partition(_INDEX_END)
        new = f"{before}{_INDEX_START}\n{body}\n{_INDEX_END}{after}"
    else:
        new = f"# Journal — research findings index\n\n{_INDEX_START}\n{body}\n{_INDEX_END}\n"
    idx.write_text(new)


def regenerate_views(config) -> None:
    """Rebuild by_topic/ and digests/ pages. Idempotent."""
    jd = _require_journal_dir(config)
    entries = all_entries(config)
    order = {o: i for i, o in enumerate(config.outcomes)}

    def okey(o: str) -> int:
        return order.get(o, len(order))

    # by_topic
    bt = jd / "by_topic"
    bt.mkdir(exist_ok=True)
    by_topic: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        by_topic[e.topic].append(e)
    for topic, es in by_topic.items():
        es = sorted(es, key=lambda e: (okey(e.outcome), e.date), reverse=False)
        lines = [f"# {config.topic_label}: {topic}", "", f"_{len(es)} entries_", ""]
        cur_out = None
        for e in sorted(es, key=lambda e: (okey(e.outcome), e.date)):
            if e.outcome != cur_out:
                cur_out = e.outcome
                lines += ["", f"## {cur_out}", ""]
            lines.append(f"- {e.date} [{e.title}](../entries/{e.id}.md) — {e.tldr}")
        (bt / f"{_safe_topic(topic)}.md").write_text("\n".join(lines) + "\n")
    rd = ["# Topics", "", "| topic | entries | last |", "|---|--:|---|"]
    for topic in sorted(by_topic, key=lambda t: -len(by_topic[t])):
        es = by_topic[topic]
        last = max(e.date for e in es)
        rd.append(f"| [{topic}]({_safe_topic(topic)}.md) | {len(es)} | {last} |")
    (bt / "README.md").write_text("\n".join(rd) + "\n")

    # digests
    dg = jd / "digests"
    dg.mkdir(exist_ok=True)
    by_month: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        if len(e.date) >= 7:
            by_month[e.date[:7]].append(e)
    for month, es in by_month.items():
        lines = [f"# {month}", "", f"_{len(es)} entries_", ""]
        per_topic: dict[str, list[Entry]] = defaultdict(list)
        for e in es:
            per_topic[e.topic].append(e)
        for topic in sorted(per_topic):
            lines += ["", f"## {topic}", ""]
            for e in sorted(per_topic[topic], key=lambda e: (okey(e.outcome), e.date)):
                lines.append(f"- [{e.outcome}] [{e.title}](../entries/{e.id}.md) — {e.tldr}")
        (dg / f"{month}.md").write_text("\n".join(lines) + "\n")
    dr = ["# Digests", "", "| month | entries |", "|---|--:|"]
    for month in sorted(by_month, reverse=True):
        dr.append(f"| [{month}]({month}.md) | {len(by_month[month])} |")
    (dg / "README.md").write_text("\n".join(dr) + "\n")


def regenerate_all(config) -> None:
    regenerate_index(config)
    regenerate_views(config)


# --------------------------------------------------------------------------- #
# public: add / record / search
# --------------------------------------------------------------------------- #
def add(config, *, topic: str, outcome: str, title: str, body: str,
        tags: list[str] | None = None, evidence: list[str] | None = None,
        supersedes: str | None = None, doc_path: str | None = None,
        force_new: bool = False, extras: dict | None = None) -> Entry:
    """Create (or idempotently update) a journal entry. Returns the Entry."""
    if not topic or not outcome or not title:
        raise JournalError("topic, outcome and title are required")
    jd = _require_journal_dir(config)
    edir = jd / "entries"
    if outcome not in config.outcomes:
        print(f"[priorstates journal] WARN: outcome '{outcome}' not in {config.outcomes}; saving anyway")

    today = _dt.date.today().isoformat()
    bh = _body_hash(body.strip())
    eid = _compute_id(topic, today, body.strip())
    target = edir / f"{eid}.md"
    if target.exists() and not force_new:
        prior = _parse_entry_file(target)
        if prior and prior.body_hash == bh:
            return prior  # unchanged no-op

    doc_rel = None
    if doc_path and config.project_root:
        try:
            doc_rel = str(Path(doc_path).resolve().relative_to(config.project_root))
        except (ValueError, OSError):
            doc_rel = str(doc_path)
    elif doc_path:
        doc_rel = str(doc_path)

    entry = Entry(
        id=eid, date=today, topic=_safe_topic(topic), outcome=outcome.strip(),
        title=title.strip(), tldr=_extract_tldr(body), body_hash=bh, doc=doc_rel,
        tags=[t.strip() for t in (tags or []) if t.strip()],
        evidence=[e.strip() for e in (evidence or []) if e.strip()],
        supersedes=supersedes or None, superseded_by=None,
        commits=_commits(config), body=body.strip(), path=target, extras=extras or {},
    )
    target.write_text(_entry_to_file(entry))

    if entry.supersedes:
        pp = edir / f"{entry.supersedes}.md"
        if pp.exists():
            prior = _parse_entry_file(pp)
            if prior and prior.superseded_by != entry.id:
                prior.superseded_by = entry.id
                pp.write_text(_entry_to_file(prior))
    regenerate_all(config)
    return entry


def record_block(config, body_full: str, doc_path: str | None = None) -> Entry:
    """Parse a ``journal`` block (frontmatter + body) and record it."""
    meta, body = _split_frontmatter_body(body_full)
    if not meta:
        raise JournalError("journal block missing YAML frontmatter")
    topic = meta.get("topic") or meta.get("strategy")
    return add(config, topic=str(topic or ""), outcome=str(meta.get("outcome", "")),
               title=str(meta.get("title", "")), body=body,
               tags=[str(t) for t in (meta.get("tags") or [])],
               evidence=[str(e) for e in (meta.get("evidence") or [])],
               supersedes=str(meta.get("supersedes")) if meta.get("supersedes") else None,
               doc_path=doc_path,
               extras={k: v for k, v in meta.items()
                       if k not in _RESERVED and not k.startswith("commit_")})


def search(config, *, topic: str | None = None, outcome: str | None = None,
           tag: str | None = None, since: str | None = None, until: str | None = None,
           query: str | None = None, k: int | None = None) -> list[dict]:
    """Structured (+ optional semantic) search → list of row dicts."""
    rows = []
    for e in all_entries(config):
        if topic and e.topic != topic:
            continue
        if outcome and e.outcome != outcome:
            continue
        if tag and tag not in e.tags:
            continue
        if since and e.date < since:
            continue
        if until and e.date > until:
            continue
        rows.append({"id": e.id, "date": e.date, "topic": e.topic, "outcome": e.outcome,
                     "title": e.title, "tldr": e.tldr, "tags": ", ".join(e.tags),
                     "supersedes": e.supersedes or "", "superseded_by": e.superseded_by or "",
                     "doc": e.doc or ""})
    rows.sort(key=lambda r: r["date"], reverse=True)

    if query and config.journal_bin and config.journal_bin.exists():
        try:
            rows = _semantic_rerank(config, rows, query)
        except Exception:
            pass
    if k is not None:
        rows = rows[:int(k)]
    return rows


def _semantic_rerank(config, rows: list[dict], query: str) -> list[dict]:
    from .store import MemoryStore
    from .embedder import get_embedder
    emb = get_embedder(config)
    qv = emb.embed_one(query)
    with MemoryStore(config.journal_bin) as st:
        hits = st.search(qv, k=max(len(rows), 1), with_body=False)
    score_by_path = {h.src_path: h.score for h in hits}
    # entries indexed by their entry-file path; map row id → score via path tail
    def sc(r):
        for p, s in score_by_path.items():
            if p.endswith(f"{r['id']}.md"):
                return s
        return -1.0
    return sorted(rows, key=sc, reverse=True)
