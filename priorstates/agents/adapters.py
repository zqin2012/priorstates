"""Per-agent adapter table — the entire agent-specific surface of PriorStates.

Each adapter declares where the agent's MCP registration lives, the config
format, the registration key, and the context file(s) the pinned memory block
is rendered into. Adding a new agent = one entry here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Adapter:
    name: str
    mcp_config: Path           # file holding MCP server registrations
    mcp_format: str            # "json" | "toml"
    mcp_key: str               # top-level key (json) / table prefix (toml)
    context_files: tuple[Path, ...]  # home-level files the pinned block is written into
    home_marker: Path          # existence ⇒ agent is installed
    project_context_name: str  # per-project context filename (e.g. AGENTS.md)
    launch_cli: str = ""       # CLI to open a path in the editor (if it is one)


def _h(p: str) -> Path:
    return Path.home() / p


ADAPTERS: dict[str, Adapter] = {
    "claude": Adapter(
        name="claude",
        mcp_config=_h(".claude.json"),
        mcp_format="json",
        mcp_key="mcpServers",
        context_files=(_h(".claude/CLAUDE.md"),),
        home_marker=_h(".claude"),
        project_context_name="CLAUDE.md",
    ),
    "codex": Adapter(
        name="codex",
        mcp_config=_h(".codex/config.toml"),
        mcp_format="toml",
        mcp_key="mcp_servers",
        context_files=(_h(".codex/AGENTS.md"),),
        home_marker=_h(".codex"),
        project_context_name="AGENTS.md",
    ),
    "gemini": Adapter(
        name="gemini",
        mcp_config=_h(".gemini/settings.json"),
        mcp_format="json",
        mcp_key="mcpServers",
        context_files=(_h(".gemini/GEMINI.md"),),
        home_marker=_h(".gemini"),
        project_context_name="GEMINI.md",
    ),
    # Google Antigravity — agentic VSCode fork. MCP config lives under
    # ~/.gemini/antigravity/mcp_config.json; it reads project AGENTS.md. It also
    # has its own brain/knowledge memory, so the MCP tools are the main win.
    "antigravity": Adapter(
        name="antigravity",
        mcp_config=_h(".gemini/antigravity/mcp_config.json"),
        mcp_format="json",
        mcp_key="mcpServers",
        context_files=(),  # no reliable home markdown; project AGENTS.md only
        home_marker=_h(".gemini/antigravity"),
        project_context_name="AGENTS.md",
        launch_cli="antigravity",
    ),
}


def detect_installed() -> list[str]:
    """Which agents appear to be present on this machine."""
    return [name for name, a in ADAPTERS.items() if a.home_marker.exists()]


def pinned_targets(config) -> list[Path]:
    """Context files the pinned block should be written into (enabled agents),
    plus the per-project context files when in a project."""
    targets: list[Path] = []
    for name in config.agents_enabled:
        a = ADAPTERS.get(name)
        if not a:
            continue
        targets.extend(a.context_files)
        if config.project_root:
            targets.append(config.project_root / a.project_context_name)
    # de-dup, keep order
    seen, out = set(), []
    for t in targets:
        if str(t) not in seen:
            seen.add(str(t))
            out.append(t)
    return out
