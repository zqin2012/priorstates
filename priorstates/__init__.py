"""PriorStates — local memory + research journal + cockpit + runnable-markdown
for Claude, Codex, and Gemini.

See docs/DESIGN.md for the architecture. Subpackages:
  core/    shared engine (config, .psmem store, embedder, indexer, journal)
  memory/  semantic memory (write path, pinned-block render, high-level API)
  mdlab/   headless runnable-Markdown (parser + runner + result regions)
  agents/  Claude / Codex / Gemini adapters + installer
  mcp/     one MCP server exposing memory_* / journal_* / mdlab tools
  gui/     Tkinter desktop control panel
  cli      `priorstates` entrypoint
"""
__version__ = "0.1.0"
