# PyPI Trusted Publishing (OIDC) — one-time setup

The release workflow publishes the wheel + sdist to PyPI using **Trusted
Publishing**: GitHub Actions mints a short-lived OIDC token that PyPI verifies
against a configured publisher. **No API token is stored anywhere** — the old
`accounts/pypi_token.md` is no longer needed once this is verified.

## How it works

`.github/workflows/release.yml` has a `pypi` job that runs only on a `vX.Y.Z`
tag push. It builds the package and calls `pypa/gh-action-pypi-publish` with
`id-token: write` permission — no password, no token. PyPI accepts the upload
because the request's OIDC claims (repo, workflow) match the trusted publisher
you register below.

## One-time configuration (do this once on pypi.org)

The project `priorstates` already exists, so add the publisher to it directly:

1. Sign in to <https://pypi.org> as the project owner.
2. Go to **Your projects → priorstates → Settings → Publishing**
   (`https://pypi.org/manage/project/priorstates/settings/publishing/`).
3. Under **Add a new publisher → GitHub**, enter exactly:
   - **Owner**: `priorstates-dev`
   - **Repository**: `priorstates`
   - **Workflow name**: `release.yml`
   - **Environment**: *(leave blank)*
4. **Add**.

That's it. The next `git tag vX.Y.Z && git push github vX.Y.Z` publishes to PyPI
automatically alongside the installer builds.

> Optional hardening: set a GitHub Actions **environment** (e.g. `pypi`) with
> required reviewers, put the same name in the PyPI publisher config, and add
> `environment: pypi` to the `pypi` job. Skipped here to keep setup to one step.

## Cut a release after this is set up

```bash
# bump version, commit, then:
git tag vX.Y.Z
git push github vX.Y.Z      # triggers installers + PyPI publish in one workflow
```

No `python -m build` / `twine upload` by hand anymore.

## Retiring the old token

After the first tag-triggered PyPI publish succeeds via OIDC:

1. Delete the account-scoped token on PyPI
   (**Account settings → API tokens → revoke**).
2. Remove `accounts/pypi_token.md` (no longer referenced by any workflow).
