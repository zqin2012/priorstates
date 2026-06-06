"""Plugin loader — the open-core extension seam.

PriorStates is open source (Apache-2.0). Closed-source editions (e.g. an
enterprise build) extend it as **separate packages that register here** — the
open client never imports plugin code by name, so the dependency points *up*
(plugin → priorstates), never down. That keeps the OSS clean and fully usable
standalone.

A plugin is any installed package that exposes a ``register(registry)`` callable,
discovered two ways (both optional, both additive):

1. **Entry points** — `[project.entry-points."priorstates.plugins"]` in the
   plugin's pyproject, value ``"pkg.module:register"``. The normal path.
2. **Explicit config** — `[plugins] load = ["pkg.module:register", …]` in
   `~/.priorstates/config.toml` (handy for dev / unpackaged plugins).

The `register(registry)` function calls the small, stable Registry API below to
add CLI commands, hub-auth headers, config overrides, and import policies. The
open client ships the *call sites* as no-ops, so a plugin is purely additive.
"""
from __future__ import annotations

import importlib
import sys


class Registry:
    """The stable extension surface. Keep this small and backward-compatible —
    plugins (including paid editions) depend on it."""

    def __init__(self):
        self.edition = "community"
        self.plugins: list[str] = []          # loaded target strings
        self._commands = []                   # fn(subparsers) -> None
        self._hub_auth = []                   # fn(url) -> dict[str, str] headers
        self._config_providers = []           # fn(cfg) -> cfg
        self._import_policies = []            # fn(manifest, members, cfg) -> (ok, reasons)
        self._service_providers = []          # fn() -> dict|list[dict] managed services
        self._account_providers = []          # fn() -> {logged_in, user, hub} | None

    # -- registration API (called by plugins) ---------------------------- #
    def set_edition(self, name: str) -> None:
        self.edition = name

    def add_command(self, fn) -> None:
        """fn(subparsers) adds argparse subcommand(s); set_defaults(func=…)."""
        self._commands.append(fn)

    def hub_auth(self, fn) -> None:
        """fn(url) -> {header: value} merged into every hub request (SSO tokens)."""
        self._hub_auth.append(fn)

    def config_provider(self, fn) -> None:
        """fn(cfg) -> cfg — override/augment config (e.g. org-managed policy)."""
        self._config_providers.append(fn)

    def on_import_pack(self, fn) -> None:
        """fn(manifest, members, cfg) -> (ok: bool, reasons: list[str]).
        Return ok=False to BLOCK an import (DLP / mandatory-signed / policy)."""
        self._import_policies.append(fn)

    def add_service(self, fn) -> None:
        """fn() -> dict | list[dict] describing background service(s) the desktop
        GUI can start/stop (e.g. the Hub edition's relay). Each dict:
        {name, label, help, argv:[…], status_url?, status_key?, needs_login?,
         options?: [{flag, type:"bool"|"str", label, default?, help?, requires?,
                     generate?, secret?, danger?}]}. The GUI renders each option
        as a toggle/field and appends the chosen flags to argv on start."""
        self._service_providers.append(fn)

    def add_account_status(self, fn) -> None:
        """fn() -> {logged_in: bool, user?: str, hub?: str} | None — lets the GUI
        show sign-in state (an edition that has accounts registers this)."""
        self._account_providers.append(fn)

    # -- consumption API (called by the open client) --------------------- #
    def apply_commands(self, subparsers) -> None:
        for fn in self._commands:
            try:
                fn(subparsers)
            except Exception as e:  # a broken plugin must not break the CLI
                print(f"[priorstates] plugin command hook failed: {e}", file=sys.stderr)

    def hub_headers(self, url: str) -> dict:
        out: dict[str, str] = {}
        for fn in self._hub_auth:
            try:
                out.update(fn(url) or {})
            except Exception as e:
                print(f"[priorstates] plugin hub_auth hook failed: {e}", file=sys.stderr)
        return out

    def apply_config(self, cfg):
        for fn in self._config_providers:
            try:
                cfg = fn(cfg) or cfg
            except Exception as e:
                print(f"[priorstates] plugin config hook failed: {e}", file=sys.stderr)
        return cfg

    def services(self) -> list:
        """Flatten all plugin-registered service descriptors (for the GUI)."""
        out: list = []
        for fn in self._service_providers:
            try:
                r = fn() or []
                out.extend(r if isinstance(r, (list, tuple)) else [r])
            except Exception as e:
                print(f"[priorstates] plugin service hook failed: {e}", file=sys.stderr)
        return out

    def account_status(self) -> dict:
        """First plugin-reported account status (for the GUI), or {} if none."""
        for fn in self._account_providers:
            try:
                r = fn()
                if r:
                    return r
            except Exception as e:
                print(f"[priorstates] plugin account hook failed: {e}", file=sys.stderr)
        return {}

    def check_import(self, manifest, members, cfg) -> tuple[bool, list]:
        for fn in self._import_policies:
            try:
                ok, reasons = fn(manifest, members, cfg)
            except Exception as e:
                return False, [f"import policy hook errored: {e}"]
            if not ok:
                return False, list(reasons or ["blocked by policy"])
        return True, []


_REGISTRY: Registry | None = None


def _entry_point_targets() -> list[str]:
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="priorstates.plugins")  # selectable API (py3.10+)
        return [ep.value for ep in eps]
    except Exception:
        return []


def _load(reg: Registry, config=None) -> None:
    targets = list(_entry_point_targets())
    if config is not None:
        targets += list(getattr(config, "plugins", []) or [])
    seen = set()
    for tgt in targets:
        if tgt in seen:
            continue
        seen.add(tgt)
        module, _, attr = str(tgt).partition(":")
        try:
            mod = importlib.import_module(module)
            register = getattr(mod, attr or "register")
            register(reg)
            reg.plugins.append(tgt)
        except Exception as e:
            print(f"[priorstates] failed to load plugin {tgt!r}: {e}", file=sys.stderr)


def registry(config=None) -> Registry:
    """The process-wide plugin registry (lazy-loaded once). Pass `config` the
    first time if you want `[plugins] load = …` targets honored too."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = Registry()
        _load(_REGISTRY, config)
    return _REGISTRY
