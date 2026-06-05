"""Per-agent adapter table — the entire agent-specific surface of PriorStates.

Each adapter declares where the agent's MCP registration lives, the config
format, the registration key, and the context file(s) the pinned memory block
is rendered into. Adding a new agent = one entry here.
"""
from __future__ import annotations

import os
import sys
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


def _claude_desktop_paths() -> tuple[Path, Path]:
    """(config_file, install_marker) for Claude Desktop (separate app from Claude
    Code), per platform.

    On Windows it's usually an MSIX/Store package: writes to %APPDATA%\\Claude are
    redirected into the package's LocalCache, and that's where the app actually
    reads its config — so the standard %APPDATA%\\Claude path is wrong there. The
    package dir is the reliable 'installed' marker (it exists even before any
    config is written)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Claude"
        return base / "claude_desktop_config.json", base
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        try:
            for d in sorted((local / "Packages").glob("Claude_*")):
                if d.is_dir():
                    cfg = d / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
                    return cfg, d
        except OSError:
            pass
        appdata = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        base = appdata / "Claude"
        return base / "claude_desktop_config.json", base
    # Linux (community builds): XDG config dir.
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "Claude"
    return base / "claude_desktop_config.json", base


_CLAUDE_DESKTOP, _CLAUDE_DESKTOP_MARKER = _claude_desktop_paths()


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
    # Claude Desktop — the desktop app (NOT Claude Code). Separate MCP config
    # (%APPDATA%\Claude on Windows, ~/Library/Application Support/Claude on macOS).
    # It reads no markdown context file, so MCP tools are the whole integration.
    "claude_desktop": Adapter(
        name="claude_desktop",
        mcp_config=_CLAUDE_DESKTOP,
        mcp_format="json",
        mcp_key="mcpServers",
        context_files=(),               # Claude Desktop has no CLAUDE.md surface
        home_marker=_CLAUDE_DESKTOP_MARKER,   # package dir (MSIX) or %APPDATA%\Claude
        project_context_name="",        # no per-project context
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
