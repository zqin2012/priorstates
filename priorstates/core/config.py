"""Configuration and root discovery.

This module replaces every hardcoded workspace path in the reference tools.
Two scopes exist:

  * **global**  — ``~/.priorstates/`` (or ``$PRIORSTATES_HOME``). Holds machine-wide
    memory (identity/preferences) and the default config.
  * **project** — the nearest ancestor directory of the cwd that contains a
    ``.priorstates/`` directory. Holds project-scoped memory + the journal.

Config is read from ``~/.priorstates/config.toml`` and overlaid with
``<project>/.priorstates/config.toml`` if present. We avoid a hard TOML dependency
(Python 3.10 has no ``tomllib``) with a small subset parser, preferring
``tomllib``/``tomli`` when available.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
DEFAULT_OUTCOMES = ["winner", "decision", "gotcha", "bug", "loser", "inconclusive", "note"]
DEFAULT_MEMORY_TYPES = ["user", "preference", "project", "reference", "note"]
DEFAULT_MODEL = "bge-small-en-v1.5"
DEFAULT_AGENTS = ["claude", "codex", "gemini", "antigravity"]
PROJECT_MARKER = ".priorstates"


# --------------------------------------------------------------------------- #
# Minimal TOML reader (subset: [section], key = "str"|true|false|int|[list]).
# --------------------------------------------------------------------------- #
def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    for mod in ("tomllib", "tomli"):
        try:
            m = __import__(mod)
            return m.loads(text)
        except Exception:
            pass
    # subset fallback
    data: dict = {}
    section = data
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            section = data.setdefault(name, {})
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        section[key.strip()] = _parse_toml_value(val.strip())
    return data


def _parse_toml_value(v: str):
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_parse_toml_value(p.strip()) for p in inner.split(",") if p.strip()]
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v)
    except ValueError:
        return v


# --------------------------------------------------------------------------- #
# Config object
# --------------------------------------------------------------------------- #
@dataclass
class Config:
    home: Path
    project_root: Path | None = None
    model: str = DEFAULT_MODEL
    embed_dtype: str = "float16"
    use_daemon: bool = True
    topic_label: str = "topic"
    outcomes: list[str] = field(default_factory=lambda: list(DEFAULT_OUTCOMES))
    memory_types: list[str] = field(default_factory=lambda: list(DEFAULT_MEMORY_TYPES))
    agents_enabled: list[str] = field(default_factory=lambda: list(DEFAULT_AGENTS))
    backup_enabled: bool = False
    backup_remote: str = ""
    backup_repos: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)

    # ---- derived paths ------------------------------------------------ #
    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    @property
    def model_dir(self) -> Path:
        return self.models_dir / self.model

    @property
    def memory_global_dir(self) -> Path:
        return self.home / "memory"

    @property
    def memory_global_bin(self) -> Path:
        return self.home / "memory.psmem"

    @property
    def project_dir(self) -> Path | None:
        return (self.project_root / PROJECT_MARKER) if self.project_root else None

    @property
    def memory_project_dir(self) -> Path | None:
        return (self.project_dir / "memory") if self.project_dir else None

    @property
    def journal_dir(self) -> Path | None:
        return (self.project_dir / "journal") if self.project_dir else None

    @property
    def journal_bin(self) -> Path | None:
        return (self.project_dir / "journal.psmem") if self.project_dir else None

    def memory_dirs(self, scope: str = "all") -> list[Path]:
        """Memory source dirs for a given scope ('all'|'global'|'project')."""
        out: list[Path] = []
        if scope in ("all", "project") and self.memory_project_dir:
            out.append(self.memory_project_dir)
        if scope in ("all", "global"):
            out.append(self.memory_global_dir)
        return out

    def context_targets(self) -> list[Path]:
        """Agent context files the pinned block is rendered into (filled by
        the agents adapters; here just the default home-level set)."""
        return []


def home_dir() -> Path:
    return Path(os.environ.get("PRIORSTATES_HOME") or (Path.home() / ".priorstates")).expanduser()


def find_project_root(start: Path | str | None = None) -> Path | None:
    """Nearest ancestor of ``start`` (default cwd) that contains a ``.priorstates/``
    project dir. The global store (``$PRIORSTATES_HOME``, usually ``~/.priorstates``)
    is NOT a project — so launching from ``$HOME`` doesn't make it one."""
    try:
        p = Path(start).expanduser().resolve() if start else Path.cwd()
    except OSError:
        return None
    try:
        global_marker = home_dir().resolve()
    except OSError:
        global_marker = None
    for d in [p, *p.parents]:
        marker = d / PROJECT_MARKER
        if marker.is_dir() and (global_marker is None or marker.resolve() != global_marker):
            return d
    return None


def _apply(cfg: Config, data: dict) -> Config:
    core = data.get("core", {})
    mem = data.get("memory", {})
    jr = data.get("journal", {})
    ag = data.get("agents", {})
    bk = data.get("backup", {})
    pl = data.get("plugins", {})
    return replace(
        cfg,
        model=core.get("model", cfg.model),
        embed_dtype=core.get("embed_dtype", cfg.embed_dtype),
        use_daemon=bool(core.get("daemon", cfg.use_daemon)),
        topic_label=jr.get("topic_label", cfg.topic_label),
        outcomes=list(jr.get("outcomes", cfg.outcomes)) or cfg.outcomes,
        memory_types=list(mem.get("types", cfg.memory_types)) or cfg.memory_types,
        agents_enabled=list(ag.get("enabled", cfg.agents_enabled)),
        backup_enabled=bool(bk.get("enabled", cfg.backup_enabled)),
        backup_remote=bk.get("remote", cfg.backup_remote),
        backup_repos=list(bk.get("repos", cfg.backup_repos)),
        plugins=list(pl.get("load", cfg.plugins)),
    )


def load_config(start: Path | str | None = None,
                force_project: Path | str | None = None) -> Config:
    """Resolve global + project config into one :class:`Config`.

    ``force_project`` makes that directory the project root *directly* (honored
    even if it isn't an initialized workspace yet) — used when the user passes an
    explicit ``--project``. Otherwise the project is auto-discovered from
    ``start``/cwd.
    """
    home = home_dir()
    if force_project:
        try:
            project_root = Path(force_project).expanduser().resolve()
        except OSError:
            project_root = Path(force_project).expanduser()
    else:
        project_root = find_project_root(start)
    cfg = Config(home=home, project_root=project_root)
    cfg = _apply(cfg, _load_toml(home / "config.toml"))
    if project_root and (project_root / PROJECT_MARKER / "config.toml").exists():
        cfg = _apply(cfg, _load_toml(project_root / PROJECT_MARKER / "config.toml"))
    return cfg


DEFAULT_CONFIG_TOML = """\
# PriorStates global configuration. See docs/DESIGN.md §11.
[core]
model = "bge-small-en-v1.5"
embed_dtype = "float16"
daemon = true

[memory]
types = ["user", "preference", "project", "reference", "note"]

[journal]
topic_label = "topic"
outcomes = ["winner", "decision", "gotcha", "bug", "loser", "inconclusive", "note"]

[agents]
enabled = ["claude", "codex", "gemini", "antigravity"]

[backup]
enabled = false
remote = ""
repos = []

[plugins]
load = []
"""
