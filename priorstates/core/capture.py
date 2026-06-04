"""Free-text → structured capture for memory and journal.

Pure, deterministic, dependency-free heuristics so a user can type a plain
sentence instead of filling a form. No model, no network — the same philosophy
as the rest of PriorStates. The agent (over MCP) remains the *smart* path; this
is the local fallback used by the cockpit's quick-capture box and the
`priorstates memory|journal capture` CLI commands.
"""
from __future__ import annotations

import re


def slugify(s: str, maxwords: int = 6, maxlen: int = 48) -> str:
    words = re.findall(r"[A-Za-z0-9]+", (s or "").lower())
    return "-".join(words[:maxwords])[:maxlen].strip("-") or "note"


def parse_memory_text(text: str, valid_types) -> dict:
    """Free text → {name, type_str, description, body, pinned}.

    `#pin` (or 'important') pins; the type is guessed from cue words and
    constrained to `valid_types`; the name is slugged from the first sentence;
    the full original text becomes the body.
    """
    valid_types = list(valid_types or [])
    raw = (text or "").strip()
    low = raw.lower()
    pinned = bool(re.search(r"(^|\s)#pin\b", low) or re.search(r"\bimportant\b", low))
    cleaned = re.sub(r"(^|\s)#\w[\w-]*", " ", raw).strip()
    first = re.split(r"(?<=[.!?])\s|\n", cleaned or raw, maxsplit=1)[0].strip()
    description = first[:120]
    typ = "note"
    if "preference" in valid_types and re.search(r"\b(i prefer|prefer|i like|always|never|favou?rite|rather)\b", low):
        typ = "preference"
    elif "project" in valid_types and re.search(r"\b(this (project|repo|repository|codebase)|we use|our team|the project)\b", low):
        typ = "project"
    elif "reference" in valid_types and re.search(r"https?://", low):
        typ = "reference"
    elif "user" in valid_types and re.search(r"\b(i am|i'm|my name|my role|call me|i work)\b", low):
        typ = "user"
    if typ not in valid_types and valid_types:
        typ = "note" if "note" in valid_types else valid_types[-1]
    return dict(name=slugify(description), type_str=typ, description=description,
                body=raw, pinned=pinned)


def parse_journal_text(text: str, outcomes) -> dict:
    """Free text → {topic, outcome, title, body}.

    Outcome is the first `outcomes` word found, else a synonym match, else the
    first outcome. Topic comes from a `#tag` or `topic:` prefix, else a short
    slug. Title is the first sentence; body is the full text.
    """
    outcomes = list(outcomes or [])
    raw = (text or "").strip()
    low = raw.lower()
    outcome = next((o for o in outcomes if re.search(r"\b" + re.escape(o.lower()) + r"\b", low)), None)
    if outcome is None:
        syn = [("winner", r"\b(won|worked|works|success|improved|beat|win)\b"),
               ("loser", r"\b(failed|fail|didn'?t work|lost|worse|regress|no edge)\b"),
               ("bug", r"\b(bug|broken|crash|error|wrong)\b"),
               ("decision", r"\b(decided|decision|chose|choose|going with)\b")]
        outcome = next((o for o, pat in syn if o in outcomes and re.search(pat, low)), None)
    if outcome is None:
        outcome = outcomes[0] if outcomes else "note"
    m = re.search(r"#(\w[\w-]*)", raw)
    mt = re.match(r"\s*topic\s*[:=]\s*([^\s,;]+)", raw, re.I)
    topic = (m.group(1) if m else (mt.group(1) if mt else slugify(raw, maxwords=3, maxlen=24)))
    title_src = re.sub(r"#\w[\w-]*", "", raw).strip()
    title_src = re.sub(r"^\s*topic\s*[:=]\s*[^\s,;]+\s*", "", title_src, flags=re.I).strip()
    title = (re.split(r"(?<=[.!?])\s|\n", title_src, maxsplit=1)[0].strip()[:120]) or "note"
    return dict(topic=topic, outcome=outcome, title=title, body=raw)


def capture_memory(config, text: str) -> dict:
    """Parse free text and add a memory (unique name). Returns the add result."""
    from ..memory import api as mem
    d = parse_memory_text(text, config.memory_types)
    name, base, i = d["name"], d["name"], 2
    while mem.get_memory(config, name):
        name = f"{base}-{i}"; i += 1
    res = mem.add_memory(config, name=name, type_str=d["type_str"], description=d["description"],
                         body=d["body"], pinned=d["pinned"], scope="project")
    res.update(name=name, type=d["type_str"], pinned=d["pinned"], description=d["description"])
    return res


def capture_journal(config, text: str) -> dict:
    """Parse free text and add a journal entry. Returns id/topic/outcome/title."""
    from ..core import journal as J
    d = parse_journal_text(text, config.outcomes)
    e = J.add(config, topic=d["topic"], outcome=d["outcome"], title=d["title"], body=d["body"])
    return {"id": e.id, "topic": d["topic"], "outcome": d["outcome"], "title": d["title"],
            "path": str(e.path)}
