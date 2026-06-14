# Release CI

Two workflows build and publish PriorStates' platform installers. They run on
GitHub-hosted runners (Linux, macOS, Windows) — free for this public repo.

## `release.yml` — the release

Trigger: push a tag `vX.Y.Z` (must equal `pyproject.toml`'s `version`), or run
manually from the Actions tab.

It builds every installer from the recipes in [`packaging/`](../../packaging):

| Runner | Artifact | Recipe |
|---|---|---|
| `ubuntu-latest` | `.deb`, `.rpm`, `.tar.gz` | `packaging/build.sh` |
| `macos-latest` | `.pkg` | `packaging/macos/build-pkg.sh` |
| `windows-latest` | `Setup.exe` | `packaging/windows/priorstates.iss` (Inno Setup) |

…then attaches them all to a GitHub Release with a `SHA256SUMS`, **plus
stable-named copies** (`PriorStates-Setup.exe`, `priorstates-latest.*`) so the
`releases/latest/download/<name>` URLs are version-free.

**Installers ship unsigned by default** (no secrets required). To code-sign +
notarize, fill in the secrets named in the commented blocks of `release.yml`
(Apple Developer ID + App Store Connect key for macOS; an Authenticode cert —
e.g. free-for-OSS [SignPath](https://signpath.io) — for Windows). Nothing else
changes.

## Where downloads are served

GitHub Releases host the installers. The website keeps branded
`priorstates.com/download/...` URLs that **302-redirect** to
`releases/latest/download/<name>` (set once in nginx) — so there is **no mirror
step and no deploy key in CI**. The last `release.yml` step just curls those
branded URLs to confirm the new release is reachable.

## Cutting a release

```bash
# bump version, publish the wheel to PyPI, then:
git commit -am "release X.Y.Z" && git push
git tag vX.Y.Z && git push origin vX.Y.Z      # CI does the rest
```

The maintainer runbook (build hosts, signing, infra) lives outside this public
repo.
