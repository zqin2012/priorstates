"""Idempotent wiring of PriorStates into Claude / Codex / Gemini.

For each enabled+present agent we (1) register the PriorStates MCP server in that
agent's config and (2) render the pinned-memory block into its context file(s).
Both are reversible via :func:`uninstall`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .adapters import ADAPTERS, Adapter, detect_installed

SERVER_NAME = "priorstates"
TOML_BEGIN = "# >>> priorstates mcp (managed) >>>"
TOML_END = "# <<< priorstates mcp (managed) <<<"
TOML_BLOCK_RE = re.compile(re.escape(TOML_BEGIN) + r".*?" + re.escape(TOML_END), re.DOTALL)

# Standing instruction that teaches the agent WHEN/HOW to use the journal +
# memory. Written into each agent's context file as its own managed block, so
# the research loop works without the user hand-editing anything.
PROTOCOL_BEGIN = "<!-- BEGIN priorstates: protocol (auto-generated, do not edit) -->"
PROTOCOL_END = "<!-- END priorstates: protocol -->"


def render_protocol_block(config) -> str:
    outcomes = " | ".join(config.outcomes)
    return f"""{PROTOCOL_BEGIN}
# PriorStates research protocol

You have PriorStates MCP tools for durable **memory** and a research **journal**.
Use them as part of normal work — recall before you answer, record as you go.

1. **Recall first.** At the start of a task — and whenever the user asks
   anything that could relate to their saved notes, preferences, or project
   facts — call `memory_search` (and `journal_search` for prior findings)
   **before you answer**. Do not rely on general knowledge alone when the user
   may have stored specific guidance. (Pinned memories are already in your
   context; `memory_search` surfaces everything else.)
2. **Before non-trivial work**, also `journal_search` by `topic` to see what's
   been tried — don't repeat a known *loser* or contradict a recorded
   *decision*.
3. **When you reach a durable conclusion** (a result, a fix, a ruled-out
   hypothesis, a decision, or a gotcha), call `journal_add`:
   - `topic`: the feature/area as stable kebab-case (e.g. `auth-refactor`)
   - `outcome`: one of {outcomes}
   - `title`: one line; `body`: start with `**TL;DR**:` and the headline result
     (include the number/metric when there is one)
   - add `tags`, `evidence` (paths/PRs), and `supersedes` (a prior entry id)
     when relevant
4. **When you learn a durable user preference or project fact**, call
   `memory_add` (`type` = preference | project | user | reference | note). Set
   `pinned: true` for standing rules the user should never have to restate.

Keep entries short and specific. One finding per entry.
{PROTOCOL_END}
"""


def _server_spec(config) -> dict:
    spec = {"command": sys.executable, "args": ["-m", "priorstates.mcp.server"]}
    env = {"PRIORSTATES_HOME": str(config.home)}
    spec["env"] = env
    return spec


# --------------------------------------------------------------------------- #
# JSON-config agents (claude, gemini)
# --------------------------------------------------------------------------- #
def _json_register(adapter: Adapter, spec: dict) -> str:
    p = adapter.mcp_config
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
    servers = data.setdefault(adapter.mcp_key, {})
    before = json.dumps(servers.get(SERVER_NAME), sort_keys=True)
    servers[SERVER_NAME] = spec
    after = json.dumps(servers[SERVER_NAME], sort_keys=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "unchanged" if before == after else "registered"


def _json_unregister(adapter: Adapter) -> str:
    p = adapter.mcp_config
    if not p.exists():
        return "absent"
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception:
        return "absent"
    servers = data.get(adapter.mcp_key, {})
    if SERVER_NAME in servers:
        del servers[SERVER_NAME]
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return "removed"
    return "absent"


# --------------------------------------------------------------------------- #
# TOML-config agents (codex) — managed marker block
# --------------------------------------------------------------------------- #
def _toml_register(adapter: Adapter, spec: dict) -> str:
    p = adapter.mcp_config
    args = ", ".join(json.dumps(a) for a in spec["args"])
    env_lines = "\n".join(f'{k} = {json.dumps(v)}' for k, v in spec.get("env", {}).items())
    block = (
        f"{TOML_BEGIN}\n"
        f"[{adapter.mcp_key}.{SERVER_NAME}]\n"
        f'command = {json.dumps(spec["command"])}\n'
        f"args = [{args}]\n"
        + (f"[{adapter.mcp_key}.{SERVER_NAME}.env]\n{env_lines}\n" if env_lines else "")
        + f"{TOML_END}\n"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = p.read_text(encoding="utf-8") if p.exists() else ""
    if TOML_BEGIN in cur:
        new = TOML_BLOCK_RE.sub(block.rstrip("\n"), cur)
        status = "unchanged" if new == cur else "registered"
    else:
        sep = "" if (not cur or cur.endswith("\n")) else "\n"
        new = cur + sep + "\n" + block
        status = "registered"
    p.write_text(new, encoding="utf-8")
    return status


def _toml_unregister(adapter: Adapter) -> str:
    p = adapter.mcp_config
    if not p.exists():
        return "absent"
    cur = p.read_text(encoding="utf-8")
    if TOML_BEGIN not in cur:
        return "absent"
    new = TOML_BLOCK_RE.sub("", cur).rstrip("\n") + "\n"
    p.write_text(new, encoding="utf-8")
    return "removed"


def _register(adapter: Adapter, spec: dict) -> str:
    return _toml_register(adapter, spec) if adapter.mcp_format == "toml" else _json_register(adapter, spec)


def _unregister(adapter: Adapter) -> str:
    return _toml_unregister(adapter) if adapter.mcp_format == "toml" else _json_unregister(adapter)


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #
def _resolve_agents(config, agents):
    if agents:
        return [a for a in agents if a in ADAPTERS]
    present = set(detect_installed())
    return [a for a in config.agents_enabled if a in ADAPTERS and (a in present or not present)]


def _agent_context_targets(config, a) -> list[Path]:
    targets = list(a.context_files)
    if config.project_root:
        targets.append(config.project_root / a.project_context_name)
    return targets


def install(config, agents: list[str] | None = None, *, protocol: bool = True) -> list[dict]:
    from ..memory.api import render_pinned, reindex
    from ..memory.pinned import write_marked_block
    # make sure pinned block reflects current memories
    try:
        reindex(config, "all")
    except Exception:
        pass
    spec = _server_spec(config)
    proto = render_protocol_block(config)
    out = []
    for name in _resolve_agents(config, agents):
        a = ADAPTERS[name]
        mcp_status = _register(a, spec)
        targets = _agent_context_targets(config, a)
        _, n = render_pinned(config, targets=targets)
        if protocol:
            for t in targets:
                write_marked_block(t, proto, PROTOCOL_BEGIN, PROTOCOL_END)
        out.append({"agent": name, "mcp": mcp_status, "context_files": [str(t) for t in targets],
                    "pinned": n, "protocol": protocol})
    return out


def uninstall(config, agents: list[str] | None = None) -> list[dict]:
    from ..memory.pinned import remove_block, remove_marked_block
    out = []
    for name in (agents or list(ADAPTERS)):
        a = ADAPTERS.get(name)
        if not a:
            continue
        mcp_status = _unregister(a)
        targets = _agent_context_targets(config, a)
        removed = []
        for t in targets:
            r1 = remove_block(t)
            r2 = remove_marked_block(t, PROTOCOL_BEGIN, PROTOCOL_END)
            if r1 or r2:
                removed.append(str(t))
        out.append({"agent": name, "mcp": mcp_status, "blocks_removed": removed})
    return out


def protocol(config, agents: list[str] | None = None, *, on: bool = True) -> list[dict]:
    """Add or remove just the research-protocol instruction block (no MCP changes)."""
    from ..memory.pinned import write_marked_block, remove_marked_block
    block = render_protocol_block(config)
    out = []
    for name in _resolve_agents(config, agents):
        a = ADAPTERS[name]
        targets = _agent_context_targets(config, a)
        for t in targets:
            if on:
                write_marked_block(t, block, PROTOCOL_BEGIN, PROTOCOL_END)
            else:
                remove_marked_block(t, PROTOCOL_BEGIN, PROTOCOL_END)
        out.append({"agent": name, "protocol": on, "context_files": [str(t) for t in targets]})
    return out


def mcp_importable() -> bool:
    """Whether the MCP server can actually start (the `mcp` package is present).
    Registration in an agent's config is useless if this is False."""
    try:
        import importlib.util
        return importlib.util.find_spec("mcp") is not None
    except Exception:
        return False


def status(config) -> list[dict]:
    present = set(detect_installed())
    runnable = mcp_importable()
    out = []
    for name, a in ADAPTERS.items():
        registered = False
        if a.mcp_config.exists():
            txt = a.mcp_config.read_text(encoding="utf-8", errors="replace")
            registered = (SERVER_NAME in txt) and (
                TOML_BEGIN in txt if a.mcp_format == "toml" else f'"{SERVER_NAME}"' in txt
            )
        out.append({"agent": name, "installed": name in present,
                    "enabled": name in config.agents_enabled, "mcp_registered": registered,
                    "mcp_runnable": runnable, "config": str(a.mcp_config)})
    return out
