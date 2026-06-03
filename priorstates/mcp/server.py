"""PriorStates MCP server (stdio).

One server, namespaced tools. Wired into Claude / Codex / Gemini by
``priorstates agents install``. Config is resolved from the launch cwd (so the
agent's workspace becomes the project scope) overlaid on ``$PRIORSTATES_HOME``.

Run directly:  ``python -m priorstates.mcp.server``
"""
from __future__ import annotations

import json

from ..core.config import load_config
from ..core import journal as J
from ..memory import api as mem
from ..mdlab import run_file


def _cfg():
    # Re-resolve per call is cheap and keeps project detection honest if the
    # agent changes directories; here we resolve once at startup.
    return load_config()


def build_server():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("priorstates")
    cfg = _cfg()

    # ----- memory ------------------------------------------------------- #
    @server.tool()
    def memory_search(query: str, k: int = 5, type: str | None = None, scope: str = "all") -> str:
        """Semantically search the user's memories. scope ∈ all|global|project."""
        return json.dumps(mem.search_memory(cfg, query, k=k, type_str=type, scope=scope), indent=2)

    @server.tool()
    def memory_get(name: str, scope: str = "all") -> str:
        """Fetch one memory by exact name."""
        return json.dumps(mem.get_memory(cfg, name, scope=scope))

    @server.tool()
    def memory_add(name: str, type: str, description: str, body: str,
                   pinned: bool = False, scope: str = "project") -> str:
        """Create a durable memory. type ∈ user|preference|project|reference|note.
        Use 'project' scope for project facts, 'global' for identity/preferences."""
        return json.dumps(mem.add_memory(cfg, name=name, type_str=type, description=description,
                                         body=body, pinned=pinned, scope=scope))

    @server.tool()
    def memory_delete(name: str, scope: str = "all") -> str:
        """Delete a memory by exact name."""
        return json.dumps(mem.delete_memory(cfg, name, scope=scope))

    @server.tool()
    def memory_pin(name: str, pinned: bool = True, scope: str = "all") -> str:
        """Pin/unpin a memory (pinned memories are injected into every session)."""
        return json.dumps(mem.pin_memory(cfg, name, pinned=pinned, scope=scope))

    @server.tool()
    def memory_list_pinned(scope: str = "all") -> str:
        """List pinned memories."""
        return json.dumps(mem.list_pinned(cfg, scope=scope), indent=2)

    # ----- journal ------------------------------------------------------ #
    @server.tool()
    def journal_search(topic: str | None = None, outcome: str | None = None,
                       tag: str | None = None, since: str | None = None,
                       until: str | None = None, query: str | None = None, k: int = 20) -> str:
        """Search the research journal. Use BEFORE proposing work: has this been
        tried? was it a loser? `query` enables semantic ranking."""
        return json.dumps(J.search(cfg, topic=topic, outcome=outcome, tag=tag, since=since,
                                   until=until, query=query, k=k), indent=2)

    @server.tool()
    def journal_add(topic: str, outcome: str, title: str, body: str,
                    tags: list[str] | None = None, evidence: list[str] | None = None,
                    supersedes: str | None = None) -> str:
        """Record a durable finding. outcome ∈ winner|decision|gotcha|bug|loser|
        inconclusive|note. Call when a session reaches a conclusion worth keeping."""
        e = J.add(cfg, topic=topic, outcome=outcome, title=title, body=body,
                  tags=tags, evidence=evidence, supersedes=supersedes)
        return json.dumps({"id": e.id, "path": str(e.path), "outcome": e.outcome})

    @server.tool()
    def journal_regen() -> str:
        """Regenerate INDEX.md, by_topic/, and digests/ from entries."""
        J.regenerate_all(cfg)
        return json.dumps({"ok": True})

    # ----- mdlab -------------------------------------------------------- #
    @server.tool()
    def mdlab_run(path: str) -> str:
        """Run all runnable blocks in a .mdlab.md/.md file and write results back."""
        return json.dumps(run_file(path, cfg))

    return server


def main():
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
