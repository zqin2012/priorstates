"""The promotion gate: tag memories, then export only the tagged subset.

Exercises `memory add --tag`, `memory tag`, and `pack export --tag/--type`
end to end through the public api/share layer, plus a round-trip import to prove
the filtered bundle is valid and provenance-stamped.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from priorstates.core import share  # noqa: E402
from priorstates.core.config import Config  # noqa: E402
from priorstates.memory import api as mem  # noqa: E402
from priorstates.memory import writer  # noqa: E402


def _cfg(tmp_path: Path) -> Config:
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (proj / ".priorstates").mkdir(parents=True)
    (home / ".priorstates").mkdir(parents=True)
    # no agent context files to render the pinned block into — isolates these
    # tests from the agent-wiring side effect of add_memory's render_pinned.
    return Config(home=home, project_root=proj, agents_enabled=[])


def test_parse_tags_forms():
    assert writer.parse_tags("[promoted, reviewed]") == ["promoted", "reviewed"]
    assert writer.parse_tags("promoted, reviewed") == ["promoted", "reviewed"]
    assert writer.parse_tags("promoted reviewed") == ["promoted", "reviewed"]
    assert writer.parse_tags("PROMOTED, promoted") == ["promoted"]  # de-dup + lower
    assert writer.parse_tags("") == []
    assert writer.parse_tags(None) == []


def test_promotion_gate_export(tmp_path):
    cfg = _cfg(tmp_path)
    # three memories: one promoted at add-time, one promoted later, one provisional
    mem.add_memory(cfg, name="model M v3 live on 5A", type_str="project",
                   description="validated", body="coefs sha…; rollback R",
                   scope="project", tags=["promoted"])
    mem.add_memory(cfg, name="feature F looks interesting", type_str="project",
                   description="provisional", body="corr in Sep-Oct; sim flat",
                   scope="project")
    mem.add_memory(cfg, name="param P retune candidate", type_str="note",
                   description="provisional", body="maybe",
                   scope="project")
    # promote one of the provisional ones after the fact
    res = mem.tag_memory(cfg, "param P retune candidate", ["promoted"], scope="project")
    assert res["tags"] == ["promoted"]

    # unfiltered export carries all three
    full = share.export_pack(cfg, scope="project", out_path=tmp_path / "full.pspack")
    mfull, _ = share.read_bundle(full)
    assert len(mfull["memory"]) == 3
    assert "selection" not in mfull

    # the promotion gate: export only `promoted`
    gated = share.export_pack(cfg, scope="project", tags=["promoted"],
                                   out_path=tmp_path / "promoted.pspack")
    mg, _ = share.read_bundle(gated)
    names = sorted(m["name"] for m in mg["memory"])
    assert names == ["model M v3 live on 5A", "param P retune candidate"]
    assert mg["selection"]["tags"] == ["promoted"]
    assert mg["selection"]["skipped_memory"] == 1
    assert "feature F" not in " ".join(names)  # provisional did NOT cross
    assert "filtered export" in share.summarize(mg)


def test_promotion_gate_roundtrip_import(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="promoted fact", type_str="project", description="d",
                   body="b", scope="project", tags=["promoted"])
    mem.add_memory(cfg, name="provisional fact", type_str="project", description="d",
                   body="b", scope="project")
    gated = share.export_pack(cfg, scope="project", tags=["promoted"],
                                   out_path=tmp_path / "g.pspack", name="strat-pack",
                                   author="research")

    # import into a fresh strategy area
    cfg2 = _cfg(tmp_path / "other")
    res = share.import_pack(cfg2, gated)
    assert res["memory_added"] == 1
    got = mem.get_memory(cfg2, "promoted fact")
    assert got is not None
    # provenance stamped, not auto-pinned
    raw = Path(got["path"]).read_text() if "path" in got else ""
    files = list(Path(cfg2.memory_project_dir).glob("*.md"))
    text = next(p.read_text() for p in files if "promoted fact" in p.read_text())
    assert "source:" in text and "strat-pack" in text
    assert "pinned: true" not in text


def test_type_filter(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="a proj", type_str="project", description="d", body="b", scope="project")
    mem.add_memory(cfg, name="a note", type_str="note", description="d", body="b", scope="project")
    out = share.export_pack(cfg, scope="project", types=["project"],
                                 out_path=tmp_path / "t.pspack")
    m, _ = share.read_bundle(out)
    assert [x["name"] for x in m["memory"]] == ["a proj"]


def _publish_args(**kw):
    import argparse
    ns = argparse.Namespace(action="publish", scope="project", name="strat-pack",
                            author="research", tag=None, types=None, list=False,
                            hub="http://fake-hub/w")
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_publish_gate_uploads_only_promoted(tmp_path, monkeypatch):
    """`pack publish --tag promoted` uploads only the gated subset."""
    import io
    import json
    import urllib.request

    from priorstates import cli

    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="promoted fact", type_str="project", description="d",
                   body="b", scope="project", tags=["promoted"])
    mem.add_memory(cfg, name="provisional fact", type_str="project", description="d",
                   body="b", scope="project")
    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)

    captured = {}

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        captured["bytes"] = req.data  # the uploaded .pspack
        return _Resp(json.dumps({"id": "abc123", "url": "http://fake-hub/w/abc123.pspack",
                                 "token": "tok", "listed": False}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    cli.cmd_pack(_publish_args(tag=["promoted"]))

    manifest, _ = share.read_bundle(captured["bytes"])
    names = [m["name"] for m in manifest["memory"]]
    assert names == ["promoted fact"]                       # provisional did NOT cross
    assert manifest["selection"]["tags"] == ["promoted"]


def test_publish_refuses_empty_selection(tmp_path, monkeypatch):
    """A gated publish that matches nothing must not upload an empty bundle."""
    import urllib.request

    import pytest

    from priorstates import cli

    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="provisional", type_str="project", description="d",
                   body="b", scope="project")
    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)

    def boom(*a, **k):
        raise AssertionError("must not hit the hub on an empty selection")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(SystemExit) as ei:
        cli.cmd_pack(_publish_args(tag=["nonexistent"]))
    assert ei.value.code == 2


def test_unpublish_uses_saved_token(tmp_path, monkeypatch):
    """`pack unpublish <id>` sends a token-authed DELETE and forgets it."""
    import argparse
    import json
    import urllib.request

    from priorstates import cli

    cfg = _cfg(tmp_path)
    (cfg.home / "published.json").write_text(json.dumps({
        "abc123": {"url": "http://fake-hub/w/abc123.pspack", "token": "edit-tok", "name": "x"}}))
    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)

    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def fake_urlopen(req, timeout=0):
        seen["method"] = req.get_method()
        seen["url"] = req.full_url
        seen["token"] = req.get_header("X-edit-token")
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    # accept a full URL too — should resolve to the bare id
    ns = argparse.Namespace(action="unpublish", id="http://fake-hub/w/abc123.pspack",
                            token=None, hub="http://fake-hub/w")
    cli.cmd_pack(ns)

    assert seen["method"] == "DELETE"
    assert seen["url"] == "http://fake-hub/w/abc123"
    assert seen["token"] == "edit-tok"
    # token forgotten after a successful unpublish
    reg = json.loads((cfg.home / "published.json").read_text())
    assert "abc123" not in reg


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
