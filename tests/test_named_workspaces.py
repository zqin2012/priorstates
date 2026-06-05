"""Named workspaces (areas): per-area global memory, shared model/identity."""
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from priorstates.core import config as cfgmod  # noqa: E402
from priorstates.core.config import Config  # noqa: E402
from priorstates.memory import api as mem  # noqa: E402


def _root(tmp_path):
    home = tmp_path / "home"
    (home).mkdir(parents=True)
    return Config(home=home, project_root=None, agents_enabled=[])


def test_area_redirects_global_memory_but_shares_model(tmp_path):
    root = _root(tmp_path)
    strat = replace(root, area="strategy")
    research = replace(root, area="research")

    assert root.memory_global_dir == tmp_path / "home" / "memory"
    assert strat.memory_global_dir == tmp_path / "home" / "workspaces" / "strategy" / "memory"
    assert research.memory_global_dir == tmp_path / "home" / "workspaces" / "research" / "memory"
    # model cache + bin location stay shared on the root home
    assert strat.models_dir == root.models_dir == tmp_path / "home" / "models"
    assert strat.memory_global_bin == tmp_path / "home" / "workspaces" / "strategy" / "memory.psmem"


def test_areas_are_isolated(tmp_path):
    root = _root(tmp_path)
    strat = replace(root, area="strategy")
    research = replace(root, area="research")

    mem.add_memory(strat, name="promoted model M", type_str="project",
                   description="live", body="rollback R", scope="global")
    mem.add_memory(research, name="provisional feature F", type_str="project",
                   description="prov", body="corr only", scope="global")

    # each area sees only its own memory
    assert mem.get_memory(strat, "promoted model M") is not None
    assert mem.get_memory(strat, "provisional feature F") is None
    assert mem.get_memory(research, "provisional feature F") is not None
    assert mem.get_memory(research, "promoted model M") is None
    # the default/root store sees neither
    assert mem.get_memory(root, "promoted model M") is None

    assert set(cfgmod.list_areas(root.home)) == {"strategy", "research"}


def test_safe_area_sanitizes(monkeypatch):
    assert cfgmod.safe_area("Core Dev!") == "core-dev"
    assert cfgmod.safe_area("../etc") == "etc"
    assert cfgmod.safe_area("") is None
    assert cfgmod.safe_area(None) is None
    monkeypatch.setenv("PRIORSTATES_WORKSPACE", "Strategy")
    assert cfgmod.current_area() == "strategy"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
