"""The open-core plugin seam: Registry API + loader."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from priorstates.core import plugins  # noqa: E402


def test_registry_hooks():
    reg = plugins.Registry()
    calls = []
    reg.add_command(lambda sub: calls.append("cmd"))
    reg.hub_auth(lambda url: {"Authorization": "Bearer XYZ"})
    reg.on_import_pack(lambda m, mem, cfg: (False, ["no PHI allowed"]))

    reg.apply_commands(object())
    assert calls == ["cmd"]
    assert reg.hub_headers("http://hub/w") == {"Authorization": "Bearer XYZ"}
    ok, reasons = reg.check_import({}, {}, None)
    assert ok is False and "no PHI" in reasons[0]


def test_import_policy_allows_when_no_plugin():
    reg = plugins.Registry()
    ok, reasons = reg.check_import({}, {}, None)
    assert ok is True and reasons == []


def test_a_broken_hook_does_not_crash():
    reg = plugins.Registry()
    reg.hub_auth(lambda url: 1 / 0)            # raises
    assert reg.hub_headers("http://x") == {}    # swallowed, no crash


def test_loader_from_config():
    mod = types.ModuleType("ps_fake_ee")

    def register(reg):
        reg.set_edition("enterprise")
        reg.add_command(lambda sub: None)
        reg.hub_auth(lambda url: {"Authorization": "Bearer fromplugin"})

    mod.register = register
    sys.modules["ps_fake_ee"] = mod
    try:
        reg = plugins.Registry()
        cfg = types.SimpleNamespace(plugins=["ps_fake_ee:register"])
        plugins._load(reg, cfg)
        assert reg.edition == "enterprise"
        assert "ps_fake_ee:register" in reg.plugins
        assert reg.hub_headers("http://h") == {"Authorization": "Bearer fromplugin"}
    finally:
        sys.modules.pop("ps_fake_ee", None)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
