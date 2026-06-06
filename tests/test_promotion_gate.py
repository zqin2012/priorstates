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



if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
