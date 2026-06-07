"""Trust graph — Phase 2 (edges & near-duplicates).

Graph edges (supersedes/contradicts/corroborates/relates) become first-class with
auto-written mirrors; recall resolves them in a post-rank pass — dropping claims
superseded by a present claim, demoting+flagging the loser of a contradiction, and
counting corroboration. Near-duplicate detection surfaces overlap at write time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from priorstates.core.config import Config  # noqa: E402
from priorstates.core.indexer import _parse_frontmatter, _parse_list  # noqa: E402
from priorstates.memory import api as mem  # noqa: E402


def _cfg(tmp_path: Path) -> Config:
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (proj / ".priorstates").mkdir(parents=True)
    (home / ".priorstates").mkdir(parents=True)
    return Config(home=home, project_root=proj, agents_enabled=[])


def _fm(cfg, name):
    return mem.show_memory(cfg, name)["frontmatter"]


def _id(cfg, name):
    return _fm(cfg, name)["id"]


# ---- edges + mirrors ------------------------------------------------------- #

def test_link_writes_mirror(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="A", type_str="note", description="", body="claim a")
    mem.add_memory(cfg, name="B", type_str="note", description="", body="claim b")
    mem.link_memory(cfg, "A", "supersedes", "B")
    assert _id(cfg, "B") in _parse_list(_fm(cfg, "A").get("supersedes"))
    assert _id(cfg, "A") in _parse_list(_fm(cfg, "B").get("superseded_by"))


def test_unlink_removes_both_sides(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="A", type_str="note", description="", body="claim a")
    mem.add_memory(cfg, name="B", type_str="note", description="", body="claim b")
    mem.link_memory(cfg, "A", "contradicts", "B")
    assert _parse_list(_fm(cfg, "A").get("contradicts"))
    mem.link_memory(cfg, "A", "contradicts", "B", remove=True)
    assert not _parse_list(_fm(cfg, "A").get("contradicts"))
    assert not _parse_list(_fm(cfg, "B").get("contradicts"))


def test_relates_writes_condition(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="quiet", type_str="note", description="", body="wins on quiet days")
    mem.add_memory(cfg, name="hivol", type_str="note", description="", body="loses on hi-vol days")
    mem.link_memory(cfg, "quiet", "relates", "hivol", condition="regime")
    assert _fm(cfg, "quiet").get("condition") == "regime"


# ---- recall post-rank ------------------------------------------------------ #

def test_superseded_dropped_from_recall(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="old view", type_str="note", description="alpha topic",
                   body="alpha topic profitable")
    mem.add_memory(cfg, name="new view", type_str="note", description="alpha topic",
                   body="alpha topic loses")
    mem.link_memory(cfg, "new view", "supersedes", "old view")
    names = [h["name"] for h in mem.search_memory(cfg, "alpha topic", k=5)]
    assert "new view" in names and "old view" not in names


def test_contradiction_demotes_and_flags_loser(tmp_path):
    cfg = _cfg(tmp_path)
    # "works" is grounded (higher trust) than "broken"
    mem.add_memory(cfg, name="works", type_str="note", description="signal s",
                   body="signal s works", evidence=["run:x"])
    mem.add_memory(cfg, name="broken", type_str="note", description="signal s",
                   body="signal s works", confidence=0.3)
    mem.link_memory(cfg, "works", "contradicts", "broken")
    hits = {h["name"]: h for h in mem.search_memory(cfg, "signal s works", k=5)}
    assert hits["works"]["score"] >= hits["broken"]["score"]
    assert hits["broken"]["contradicted"] is True


def test_corroboration_counted(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="claim", type_str="note", description="topic t", body="topic t result")
    mem.add_memory(cfg, name="independent", type_str="note", description="topic t", body="topic t result too")
    mem.link_memory(cfg, "claim", "corroborates", "independent")
    hits = {h["name"]: h for h in mem.search_memory(cfg, "topic t result", k=5)}
    assert hits["claim"].get("corroboration_count", 0) >= 1


def test_no_edges_means_no_postrank_change(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="x", type_str="note", description="", body="plain claim one")
    mem.add_memory(cfg, name="y", type_str="note", description="", body="plain claim two")
    hits = mem.search_memory(cfg, "plain claim", k=2)
    assert {h["name"] for h in hits} == {"x", "y"}
    assert all(h["has_edges"] is False for h in hits)


# ---- near-duplicate detection ---------------------------------------------- #

def test_find_near_dups(tmp_path):
    cfg = _cfg(tmp_path)
    mem.add_memory(cfg, name="original", type_str="note", description="dup body here",
                   body="dup body here")
    mem.add_memory(cfg, name="copycat", type_str="note", description="dup body here",
                   body="dup body here")
    dups = mem.find_near_dups(cfg, name="original", threshold=0.5)
    assert any(d["name"] == "copycat" for d in dups)
    # nothing is similar to an unrelated claim
    mem.add_memory(cfg, name="unrelated", type_str="note", description="",
                   body="completely different subject matter")
    assert mem.find_near_dups(cfg, name="unrelated", threshold=0.9) == []
