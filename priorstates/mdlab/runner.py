"""Headless mdlab runner.

Runs the runnable blocks in a Markdown file and writes results back into
``<!-- priorstates:result ... -->`` regions. Python blocks share a persistent
namespace within a single ``run_file`` call (state carries across blocks, as in
the VSCode kernel). Bash blocks shell out. ``journal`` / ``journal-search``
blocks call the core journal engine. ``prompt`` blocks (optional) shell out to an
agent CLI.
"""
from __future__ import annotations

import hashlib
import io
import contextlib
import subprocess
import traceback
from pathlib import Path

from ..core import journal as journal_engine
from .parser import Block, parse_blocks, RUNNABLE

MARKER_OPEN = "<!-- priorstates:result src={src} kind={kind} -->"
MARKER_END = "<!-- priorstates:result-end -->"


def block_hash(kind: str, body: str) -> str:
    h = hashlib.sha1()
    h.update(kind.encode("utf-8"))
    h.update(b"\0")
    h.update(body.encode("utf-8"))
    return h.hexdigest()[:12]


# --------------------------------------------------------------------------- #
# executors
# --------------------------------------------------------------------------- #
def _run_python(body: str, ns: dict, cwd: Path) -> tuple[str, str]:
    out = io.StringIO()
    try:
        ns.setdefault("__name__", "__mdlab__")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = compile(body, "<mdlab>", "exec")
            exec(code, ns)
        return "output", out.getvalue().rstrip("\n")
    except Exception:
        return "error", (out.getvalue() + "\n" + traceback.format_exc()).strip()


def _run_bash(body: str, cwd: Path) -> tuple[str, str]:
    try:
        r = subprocess.run(["bash", "-c", body], cwd=str(cwd),
                           capture_output=True, text=True, timeout=600)
        text = (r.stdout + r.stderr).rstrip("\n")
        return ("output" if r.returncode == 0 else "error"), text
    except Exception as e:
        return "error", str(e)


def _run_journal(body: str, config, doc_path: Path) -> tuple[str, str]:
    try:
        entry = journal_engine.record_block(config, body, doc_path=str(doc_path))
        return "result", f"Journal entry recorded → entries/{entry.id}.md  ({entry.outcome})"
    except Exception as e:
        return "error", f"journal error: {e}"


def _run_journal_search(block: Block, config) -> tuple[str, str]:
    ex = block.attrs.extras
    rows = journal_engine.search(
        config, topic=ex.get("topic"), outcome=ex.get("outcome"), tag=ex.get("tag"),
        since=ex.get("since"), until=ex.get("until"), query=ex.get("query"),
        k=int(ex["limit"]) if ex.get("limit") else None,
    )
    if not rows:
        return "result", "_No matching entries._"
    lines = ["| date | outcome | topic | title | TL;DR |", "|---|---|---|---|---|"]
    for r in rows:
        tldr = r["tldr"] if len(r["tldr"]) <= 100 else r["tldr"][:99] + "…"
        lines.append(f"| {r['date']} | {r['outcome']} | {r['topic']} | "
                     f"[{r['title']}](entries/{r['id']}.md) | {tldr} |")
    return "result", "\n".join(lines)


def _run_prompt(body: str, config, cwd: Path) -> tuple[str, str]:
    import shutil
    cli = None
    for cand in ("claude", "codex", "gemini"):
        if shutil.which(cand):
            cli = cand
            break
    if cli is None:
        return "error", "no agent CLI found on PATH (claude/codex/gemini) for prompt block"
    flag = "-p" if cli in ("claude",) else "-p"
    try:
        r = subprocess.run([cli, flag, body], cwd=str(cwd),
                           capture_output=True, text=True, timeout=600)
        return ("result" if r.returncode == 0 else "error"), (r.stdout or r.stderr).strip()
    except Exception as e:
        return "error", str(e)


def _fence(kind: str, text: str) -> str:
    """Wrap output/error in a fenced block; pass markdown/result kinds through."""
    if kind in ("output", "error"):
        return f"```{kind}\n{text}\n```"
    return text  # 'result' kinds are already markdown


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #
def run_block(block: Block, config, *, ns: dict, doc_path: Path, cwd: Path) -> tuple[str, str]:
    """Execute one block → (result_kind, body_text)."""
    if block.kind == "python":
        return _run_python(block.body, ns, cwd)
    if block.kind == "bash":
        return _run_bash(block.body, cwd)
    if block.kind == "journal":
        return _run_journal(block.body, config, doc_path)
    if block.kind == "journal-search":
        return _run_journal_search(block, config)
    if block.kind == "prompt":
        return _run_prompt(block.body, config, cwd)
    return "error", f"unknown runnable kind {block.kind!r}"


def run_file(path: str | Path, config, *, only_kinds: set[str] | None = None) -> dict:
    """Run all runnable blocks in a file, writing results back. Returns a summary."""
    path = Path(path).resolve()
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    blocks = parse_blocks(text)
    ns: dict = {}
    cwd = path.parent
    ran = skipped = errors = 0
    runnable = [b for b in blocks if b.kind in RUNNABLE and (not only_kinds or b.kind in only_kinds)]

    # Pass 1 — execute in document order so python state carries across blocks
    # and journal-search sees entries recorded by earlier journal blocks.
    results: list[tuple[Block, str]] = []  # (block, region_text)
    for block in runnable:
        h = block_hash(block.kind, block.body)
        if block.attrs.cache and block.result and block.result.src == h:
            skipped += 1
            continue
        kind, body = run_block(block, config, ns=ns, doc_path=path, cwd=cwd)
        if kind == "error":
            errors += 1
        ran += 1
        region = MARKER_OPEN.format(src=h, kind=kind) + "\n" + _fence(kind, body) + "\n" + MARKER_END
        results.append((block, region))

    # Pass 2 — splice results bottom-up so line numbers stay valid as we edit.
    for block, region in sorted(results, key=lambda br: br[0].fence_open_line, reverse=True):
        if block.result:
            lines[block.result.open_line:block.result.end_line + 1] = region.split("\n")
        else:
            insert_at = block.fence_close_line + 1
            lines[insert_at:insert_at] = ["", region]
    path.write_text("\n".join(lines), encoding="utf-8")
    return {"file": str(path), "ran": ran, "skipped": skipped, "errors": errors,
            "blocks": len(runnable)}
