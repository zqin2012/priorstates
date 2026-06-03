# Homebrew formula for PriorStates (for a personal tap, not homebrew-core).
#
# Install options:
#   brew install --build-from-source ./packaging/macos/priorstates.rb   # from this checkout
#   brew install --HEAD priorstates                                     # from the git repo
#
# It creates a dedicated virtualenv under the formula's libexec and installs
# PriorStates + numpy into it, then links the `priorstates` / `priorstates-gui` commands.
class PriorStates < Formula
  include Language::Python::Virtualenv

  desc "Local memory, research journal, mdlab and cockpit for Claude/Codex/Gemini"
  homepage "https://github.com/priorstates/priorstates"
  # For a tagged release, set url+sha256 to the release tarball. Until then,
  # `brew install --HEAD` uses the git head below.
  url "https://github.com/priorstates/priorstates/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  version "0.1.0"
  license "Apache-2.0"
  head "https://github.com/priorstates/priorstates.git", branch: "main"

  depends_on "python@3.12"
  depends_on "node" => :recommended   # for the web cockpit

  def install
    venv = virtualenv_create(libexec, "python3.12")
    # Install PriorStates and its runtime deps (numpy, and optional extras) into
    # the venv from the formula source tree.
    venv.pip_install_and_link buildpath
  end

  test do
    assert_match "priorstates", shell_output("#{bin}/priorstates --help")
    system bin/"priorstates", "doctor"
  end
end
