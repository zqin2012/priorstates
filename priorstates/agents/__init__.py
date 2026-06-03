"""pm-agents — Claude / Codex / Gemini adapters + installer.

All three agents speak MCP for tools, so the memory/journal/mdlab logic is
written once (priorstates.mcp.server) and each agent differs only in (a) where its
MCP registration lives and (b) which context file the pinned block goes into.
That whole per-agent surface is the ADAPTERS table in adapters.py.
"""
from .adapters import ADAPTERS, detect_installed, pinned_targets  # noqa: F401
from .install import install, uninstall, status, protocol  # noqa: F401
