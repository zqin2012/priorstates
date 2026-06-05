# Plugins — the extension seam

PriorStates is open source (Apache-2.0). Closed-source editions and third-party
add-ons extend it as **separate packages that register here** — the open client
never imports plugin code by name, so the dependency points *up* (plugin →
priorstates), never down.

## Writing a plugin

A plugin is any installed package exposing a `register(registry)` callable:

```python
# my_plugin/__init__.py
def register(reg):
    reg.set_edition("enterprise")           # shown by `priorstates doctor`
    reg.add_command(_add_cli)               # add subcommands
    reg.hub_auth(lambda url: {"Authorization": f"Bearer {_token()}"})
    reg.on_import_pack(_policy)              # block imports by policy

def _add_cli(subparsers):
    p = subparsers.add_parser("acme", help="ACME enterprise commands")
    p.set_defaults(func=lambda args: print("hello from acme"))

def _policy(manifest, members, cfg):
    # return (ok, reasons); ok=False blocks the import
    return True, []
```

Register it for discovery — either is fine, both are additive:

```toml
# the plugin's pyproject.toml  (the normal path)
[project.entry-points."priorstates.plugins"]
acme = "my_plugin:register"
```
```toml
# or ~/.priorstates/config.toml  (handy for dev / unpackaged plugins)
[plugins]
load = ["my_plugin:register"]
```

## The Registry API (stable surface)

| Method | Hook | Called by the client at |
|---|---|---|
| `set_edition(name)` | edition label | `priorstates doctor` |
| `add_command(fn)` | `fn(subparsers)` adds argparse subcommands | `build_parser()` |
| `hub_auth(fn)` | `fn(url) -> {header: value}` merged into hub requests | every `pack` hub call (read/publish/unpublish) |
| `config_provider(fn)` | `fn(cfg) -> cfg` override/augment config | config resolution |
| `on_import_pack(fn)` | `fn(manifest, members, cfg) -> (ok, reasons)`; `ok=False` blocks | `pack import` (after the injection scan) |

This surface is intentionally small and kept backward-compatible — paid editions
depend on it. A broken hook is caught and logged, never crashes the core CLI.

## Notes

- The open client ships every hook **call site as a no-op**, so a plugin is
  purely additive and the community edition is fully functional standalone.
- `priorstates doctor` reports the active edition and loaded plugin targets.
- Keep core value in the open client; reserve plugins for org / compliance /
  scale features (SSO, policy/DLP, audit ledger, managed config, federated hub).
