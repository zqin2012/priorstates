"""Block parser, ported from the mdlab TypeScript ``parser.ts``.

Recognizes fenced blocks with an optional ``{key=value, ...}`` attribute set and
detects the result region that immediately follows a block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

RUNNABLE = {"python", "bash", "prompt", "journal", "journal-search"}

OPEN_RE = re.compile(r"^(\s*)```([\w-]+)\s*(\{[^}]*\})?\s*$")
CLOSE_RE = re.compile(r"^\s*```\s*$")
RESULT_OPEN_RE = re.compile(r"^\s*<!--\s*priorstates:result\s+src=(\S+)\s+kind=(\S+)\s*-->\s*$")
RESULT_END_RE = re.compile(r"^\s*<!--\s*priorstates:result-end\s*-->\s*$")


@dataclass
class Attrs:
    cache: bool = False
    id: str | None = None
    extras: dict[str, str] = field(default_factory=dict)
    raw: str = ""


@dataclass
class ResultRegion:
    open_line: int
    end_line: int
    src: str
    kind: str


@dataclass
class Block:
    kind: str
    attrs: Attrs
    fence_open_line: int
    fence_close_line: int
    body: str
    result: ResultRegion | None = None


def _parse_attrs(raw: str | None) -> Attrs:
    a = Attrs(raw=raw or "")
    if not raw:
        return a
    inner = raw.strip()[1:-1]  # strip { }
    for part in _split_attrs(inner):
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "cache":
            a.cache = val in ("true", "1", "yes")
        elif key == "id":
            a.id = val
        else:
            a.extras[key] = val
    return a


def _split_attrs(inner: str) -> list[str]:
    out, buf, depth, quote = [], [], 0, None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "[(":
            depth += 1
            buf.append(ch)
        elif ch in "])":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def parse_blocks(text: str) -> list[Block]:
    lines = text.split("\n")
    blocks: list[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        m = OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        kind, raw_attrs = m.group(2), m.group(3)
        open_line = i
        j = i + 1
        body_lines = []
        while j < n and not CLOSE_RE.match(lines[j]):
            body_lines.append(lines[j])
            j += 1
        if j >= n:
            break  # unterminated fence
        close_line = j
        block = Block(kind=kind, attrs=_parse_attrs(raw_attrs),
                      fence_open_line=open_line, fence_close_line=close_line,
                      body="\n".join(body_lines))
        block.result = _find_result_after(lines, close_line + 1)
        blocks.append(block)
        i = (block.result.end_line + 1) if block.result else (close_line + 1)
    return blocks


def _find_result_after(lines: list[str], start: int) -> ResultRegion | None:
    k = start
    # allow blank lines between block and its result region
    while k < len(lines) and lines[k].strip() == "":
        k += 1
    if k >= len(lines):
        return None
    m = RESULT_OPEN_RE.match(lines[k])
    if not m:
        return None
    open_line = k
    src, kind = m.group(1), m.group(2)
    k += 1
    while k < len(lines) and not RESULT_END_RE.match(lines[k]):
        k += 1
    if k >= len(lines):
        return None
    return ResultRegion(open_line=open_line, end_line=k, src=src, kind=kind)
