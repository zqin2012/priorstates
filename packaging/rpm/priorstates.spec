# Distro-agnostic noarch RPM for the open-source PriorStates core
# (RHEL/Rocky/Alma 9+, Fedora). Built by packaging/rpm/build-rpm.sh, which
# stages the payload and passes  --define "ver ..." --define "stagedir ...".
#
# Design: the payload lives in /usr/lib/priorstates (a private dir, including
# the wheel's .dist-info so the priorstates.plugins entry-point seam stays
# discoverable) and /usr/bin/priorstates picks a Python 3.10+ at runtime —
# EL9's system python3 is 3.9, so there the rich dependency below pulls in
# python3.12 instead. One RPM therefore serves EL9 / EL10 / Fedora, whose
# system pythons all differ.

%global __brp_python_bytecompile %{nil}
%global debug_package %{nil}

Name:           priorstates
Version:        %{ver}
Release:        1
Summary:        Shared AI memory, research journal & cockpit for AI agents
License:        Apache-2.0
URL:            https://github.com/zqin2012/priorstates
BuildArch:      noarch
# Manual deps only: the automatic python dependency generator would emit
# python3dist(...) requires bound to the BUILD python, which is wrong here.
AutoReqProv:    no
Requires:       (python3.12 or python3 >= 3.10)
Requires:       (python3.12-numpy if python3.12 else python3-numpy)
Recommends:     (python3.12-pip if python3.12 else python3-pip)
Recommends:     (python3.12-tkinter if python3.12 else python3-tkinter)
Conflicts:      priorstates-hub

%description
PriorStates gives AI agents (Claude Code, VSCode Copilot, Cursor, Codex,
Gemini, ...) a shared local memory, a research journal, runnable-Markdown
(mdlab) and a web cockpit, with a desktop control panel and a CLI. Install
once: every detected agent is wired over MCP and uses the memory
automatically. 100%% local, Apache-2.0.

Installs a desktop launcher in your application menu. Agent (MCP)
integration and semantic recall use extra pip packages (mcp, onnxruntime,
tokenizers).

%install
mkdir -p %{buildroot}
cp -a %{stagedir}/. %{buildroot}/

%files
/usr/lib/priorstates
%{_bindir}/priorstates
%{_bindir}/priorstates-gui
%{_datadir}/applications/priorstates.desktop
%{_datadir}/icons/hicolor/scalable/apps/priorstates.svg
%{_mandir}/man1/priorstates.1*
%{_mandir}/man1/priorstates-gui.1*
%{_datadir}/doc/priorstates

%post
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || :
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t -q /usr/share/icons/hicolor >/dev/null 2>&1 || :
# Pick the same interpreter the launcher will use (EL9: python3.12; Fedora/EL10: python3).
PSPY=python3
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 || PSPY=python3.12

# Finish setup automatically — no manual steps. The MCP/onnx libs aren't rpm
# packages, so install them into the installing user's site, wire agents, and
# fetch the semantic model. Runs as $SUDO_USER (set by `sudo dnf install`).
# Non-fatal so a network hiccup never fails the package install.
U="${SUDO_USER:-}"
if [ -n "$U" ] && [ "$U" != "root" ]; then
  H="$(getent passwd "$U" | cut -d: -f6)"
  if command -v runuser >/dev/null 2>&1; then
    asuser() { runuser -u "$U" -- env HOME="$H" PIP_BREAK_SYSTEM_PACKAGES=1 "$@"; }
  else
    asuser() { sudo -u "$U" -H env PIP_BREAK_SYSTEM_PACKAGES=1 "$@"; }
  fi
  echo "PriorStates: finishing setup for $U (MCP tools + ~127 MB semantic model)..."
  asuser $PSPY -m pip install --user -q mcp onnxruntime tokenizers \
    || echo "  note: MCP/onnx libs not installed (offline?) — later run: $PSPY -m pip install --user mcp onnxruntime tokenizers"
  asuser priorstates init >/dev/null 2>&1 || :
  asuser priorstates init --download-model \
    || echo "  note: model download deferred — later run: priorstates init --download-model"
  echo "PriorStates ready — launch it from your application menu or run: priorstates-gui"
else
cat <<MSG

PriorStates installed. Finish setup as your normal user (one line):
  PIP_BREAK_SYSTEM_PACKAGES=1 $PSPY -m pip install --user mcp onnxruntime tokenizers && priorstates init && priorstates init --download-model
Find "PriorStates" in your application menu, too.
MSG
fi
exit 0

%postun
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || :
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t -q /usr/share/icons/hicolor >/dev/null 2>&1 || :
exit 0
