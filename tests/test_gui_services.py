"""The GUI builds a service's launch argv from its plugin-declared options
(checkboxes/fields), honoring `requires` deps and `generate` secrets — so users
toggle features in the desktop app instead of typing CLI flags."""
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeVar:
    def __init__(self, value=None, **k):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _fake_tk():
    def mod(n):
        return types.ModuleType(n)
    tk = mod("tkinter")
    for n in ["Tk", "Frame", "Label", "Button", "Entry", "Text", "Listbox", "Menu",
              "Menubutton", "Checkbutton", "Canvas", "Scrollbar"]:
        setattr(tk, n, lambda *a, **k: MagicMock())
    tk.StringVar = lambda value="", **k: FakeVar(value)
    tk.BooleanVar = lambda value=False, **k: FakeVar(value)
    tk.TclError = Exception
    ttk = mod("tkinter.ttk")
    for n in ["Frame", "Label", "Button", "Entry", "Combobox", "Notebook", "LabelFrame",
              "Checkbutton", "Menubutton", "Style", "Treeview", "Scrollbar"]:
        setattr(ttk, n, lambda *a, **k: MagicMock())
    font = mod("tkinter.font")
    font.nametofont = lambda name: MagicMock()
    font.families = lambda *a, **k: ["mono"]
    sys.modules.update({"tkinter": tk, "tkinter.ttk": ttk, "tkinter.font": font})


class _Proc:
    def poll(self):
        return None

    def terminate(self):
        pass


def _gui():
    os.environ["PRIORSTATES_HOME"] = tempfile.mkdtemp()
    _fake_tk()
    from priorstates.gui import app as A
    g = A.PriorStatesGUI(MagicMock())
    g._svc_proc = {}
    return A, g


def test_options_build_argv(monkeypatch):
    A, g = _gui()
    spec = {"name": "relay", "argv": ["py", "-m", "priorstates", "relay", "connect"], "options": [
        {"flag": "--allow-write", "type": "bool"},
        {"flag": "--allow-terminal", "type": "bool"},
        {"flag": "--terminal-cmd", "type": "str", "requires": "--allow-terminal"},
        {"flag": "--terminal-pass", "type": "str", "requires": "--allow-terminal", "generate": True, "secret": True},
    ]}
    g._svc_rows = {"relay": {"opts": {
        "--allow-write": FakeVar(True), "--allow-terminal": FakeVar(True),
        "--terminal-cmd": FakeVar("claude"), "--terminal-pass": FakeVar("")}, "note": FakeVar("")}}
    cap = {}
    monkeypatch.setattr(A.subprocess, "Popen", lambda argv, **k: (cap.__setitem__("argv", argv), _Proc())[1])
    g._svc_start(spec)
    argv = cap["argv"]
    assert "--allow-write" in argv and "--allow-terminal" in argv
    assert argv[argv.index("--terminal-cmd") + 1] == "claude"
    pw = argv[argv.index("--terminal-pass") + 1]
    assert len(pw) >= 8                                  # passphrase auto-generated
    assert pw not in g._svc_rows["relay"]["note"].get()  # never shown in the GUI
    assert pw == g._svc_rows["relay"]["opts"]["--terminal-pass"].get()  # set in the (masked) field, copyable


def test_requires_skips_when_dependency_off(monkeypatch):
    A, g = _gui()
    spec = {"name": "relay", "argv": ["x"], "options": [
        {"flag": "--allow-terminal", "type": "bool"},
        {"flag": "--terminal-cmd", "type": "str", "requires": "--allow-terminal"}]}
    g._svc_rows = {"relay": {"opts": {
        "--allow-terminal": FakeVar(False), "--terminal-cmd": FakeVar("claude")}, "note": FakeVar("")}}
    cap = {}
    monkeypatch.setattr(A.subprocess, "Popen", lambda argv, **k: (cap.__setitem__("argv", argv), _Proc())[1])
    g._svc_start(spec)
    assert "--allow-terminal" not in cap["argv"]
    assert "--terminal-cmd" not in cap["argv"]            # dependency off → skipped


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
