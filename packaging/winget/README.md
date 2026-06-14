# winget publishing

PriorStates ships a signed Windows `Setup.exe`, but many corporate environments
block downloading/running `.exe` files directly. **winget** (the package manager
built into Windows 10/11) is usually allow-listed there, so we publish to it.

Package identifier: **`PriorStates.PriorStates`**

Once published, users install with:

```powershell
winget install PriorStates.PriorStates
```

(For the most locked-down setups, the no-installer path is `pipx install priorstates`.)

## One-time: first submission (manual)

winget can only *update* a package that already exists in
[`microsoft/winget-pkgs`](https://github.com/microsoft/winget-pkgs). The first
version must be submitted by hand:

1. Install the helper: `winget install Microsoft.WingetCreate`
2. Generate + submit the manifest from a released installer URL:
   ```powershell
   wingetcreate new https://github.com/priorstates-dev/priorstates/releases/download/vX.Y.Z/PriorStates-X.Y.Z-Setup.exe
   ```
   Fill in: PackageIdentifier `PriorStates.PriorStates`, Publisher `PriorStates`,
   Moniker `priorstates`, License `Apache-2.0`, homepage `https://priorstates.com`,
   InstallerType `inno`, Scope `user`. It opens a PR to `microsoft/winget-pkgs`.
3. Wait for the Microsoft validation pipeline + a maintainer to merge it.

## Ongoing: automatic per-release updates (CI)

The `winget` job in [`.github/workflows/release.yml`](../../.github/workflows/release.yml)
uses [`vedantmgoyal/winget-releaser`](https://github.com/vedantmgoyal/winget-releaser)
to open the update PR on every release. It **auto-skips** until you enable it:

- repo **variable** `WINGET_PUBLISH` = `true`
- repo **secret** `WINGET_TOKEN` = a *classic* PAT with `public_repo` scope, owned
  by a GitHub account that has **forked `microsoft/winget-pkgs`** (the action pushes
  the manifest branch to that fork, then PRs upstream).

After the first manual submission is merged and those are set, each `vX.Y.Z` tag
opens a winget update PR automatically. The job points at the **versioned** exe
(`PriorStates-X.Y.Z-Setup.exe`), not the `-latest` alias.

> Note: winget prefers signed installers. Enable SignPath (Windows code signing)
> first — see [`.github/workflows/README.md`](../../.github/workflows/README.md).
