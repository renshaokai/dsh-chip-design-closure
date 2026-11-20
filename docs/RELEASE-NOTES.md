# Release notes and publishing runbook

How this package reaches the npm registry, and the failure signatures worth
recognising next time. Written after publishing `1.13.0` and `1.13.1`.

## Current pipeline

| Piece | Value |
|---|---|
| Registry | `https://registry.npmjs.org` (`publishConfig.registry`) |
| Trigger | pushing a `v*` tag, or a manual `workflow_dispatch` |
| Workflow | `.github/workflows/publish.yml` |
| Credential | GitHub OIDC via npm trusted publishing — no token, no OTP |
| Provenance | generated automatically, `https://slsa.dev/provenance/v1` |
| Bound npm package | `dsh-chip-design-closure` (owner `clean-eco`) |

The trusted publisher entry lives on the npm package's **Settings → Trusted
Publisher** page and names `renshaokai/dsh-chip-design-closure` with workflow
file `publish.yml` and no environment. It must allow **npm publish**; the
`npm stage publish` permission is always granted and is not enough on its own.

## Releasing

```sh
npm version 1.13.2 --no-git-tag-version
git commit -am "chore: 1.13.2"
git tag v1.13.2
git push origin main
git push origin v1.13.2
```

The workflow refuses to publish when the tag and `package.json` disagree, and
prints the tarball contents before uploading.

A `workflow_dispatch` run publishes whatever `package.json` currently says, so
it only succeeds for a version that is not on the registry yet.

## Prerequisites the workflow enforces

- **npm >= 11.5.1.** Node 22 ships npm 10.9.x, which predates trusted
  publishing. The job installs npm 11 into `$RUNNER_TEMP/npm11` and prepends it
  to `PATH`; installing globally is not enough if the older binary stays first
  on `PATH`.
- **`id-token: write`.** Without it `ACTIONS_ID_TOKEN_REQUEST_URL` is absent and
  the job fails at the toolchain check instead of mysteriously needing auth.
- **`package.json` `repository.url`.** The registry compares it with the
  provenance statement's repository and rejects a mismatch.

## Failure signatures

### `ENEEDAUTH` — "This command requires you to be logged in"

```
npm error code ENEEDAUTH
npm error need auth This command requires you to be logged in to https://registry.npmjs.org
```

npm never obtained an OIDC token. Two causes, in order of likelihood:

1. the `npm` on `PATH` is older than 11.5.1 — check `npm --version` in the job;
2. `permissions: id-token: write` is missing, so `ACTIONS_ID_TOKEN_REQUEST_URL`
   is unset.

Add `--loglevel verbose` temporarily to the publish step: a working exchange
logs `npm http fetch POST 201 .../oidc/token/exchange/package/<name>` followed by
`Successfully retrieved and set token`.

### `404 OIDC token exchange error - package not found`

```
POST 404 https://registry.npmjs.org/-/npm/v1/oidc/token/exchange/package/dsh-chip-design-closure
OIDC token exchange error - package not found
```

The registry has no trusted publisher entry whose claims match the token. Check
each claim against the npm page:

- repository `owner/name` — a single wrong character is enough. A trailing `s`,
  a missing leading letter, or the old repository name all produce this error;
- workflow filename — `publish.yml`, not a path;
- environment name — must match the workflow's environment, or be empty on both
  sides.

The npm settings page renders the bound repository on the trusted publisher
card, so compare that string character by character with the GitHub URL before
publishing again. Required fields cannot be edited after creation: delete the
entry and create a new one.

### `422 Error verifying sigstore provenance bundle`

```
Failed to validate repository information: package.json: "repository.url" is "",
expected to match "https://github.com/renshaokai/dsh-chip-design-closure" from provenance
```

`package.json` had no `repository` field. Add:

```json
"repository": {
  "type": "git",
  "url": "git+https://github.com/renshaokai/dsh-chip-design-closure.git"
}
```

The OIDC exchange already succeeded at this point, so the trusted publisher
setup is fine.

### Push reports success but no workflow runs

`git push --follow-tags` only pushes **annotated** tags. A tag created with plain
`git tag` stays local and nothing triggers. Push it explicitly with
`git push origin v1.13.2`, or create annotated tags with `git tag -a`.

### Skill footers carry the wrong version after a sync

Symptom: `skills/chip-design/references/*.md` end with `<sub>… chip-arch-expert
v1.12.0 …</sub>` even though the bundle ships 1.13.0 content.

Cause, in two layers. Upstream packed 1.13.0 without bumping the footer on two
reference files (`fp-vp-generation.md`, `spec-outline.md`). The sync tool then
copied them verbatim, because its byte-identity assertion swaps the footer out
before comparing — it guarantees *the bundle faithfully copies upstream*, not
*upstream is self-consistent*. So the footer could say anything and still pass.

Fix, applied in 1.13.2:

- `do_sync` now rewrites the `<sub>… vX.Y.Z` version together with the author
  name, sourced from the upstream `plugin.json`, so a stale upstream footer
  cannot be carried down.
- `assert_footer_version` checks the **bundle** against that same version and
  reports `file:line` for each mismatch. It is deliberately independent of the
  byte-identity check, which stays blind to footers by design.
- The byte-identity check now also normalises the footer version, so the two
  assertions divide cleanly: content vs. footer.

Lesson worth keeping: any assertion that is allowed to normalise a field is
not checking that field. If the field matters to a reader, assert it separately.

### Staged publishes
Publishing with a granular access token that bypasses 2FA no longer publishes
directly; npm converts it into a staged release and waits for a 2FA approval,
which leaves the package pointing at a `0.0.0-stage` placeholder:

```
npm view dsh-chip-design-closure version   # 0.0.0-stage
```

Grep the registry metadata for `"description":"Temporary package placeholder for
staged publishing"`. `npm stage list` does not necessarily surface that record,
and `npm stage approve` needs a UUID stage id, so the practical fix is to approve
it in the browser, or to abandon the token route and use trusted publishing.

npm also restricts account and trust changes to sessions that can satisfy 2FA:

```
403 Granular access tokens that bypass two-factor authentication may not perform this action
```

`npm trust github ...` therefore cannot create the binding from a bypass token;
it has to be done on the website.

## Verifying a release

```sh
npm view dsh-chip-design-closure version --registry=https://registry.npmjs.org
npm view dsh-chip-design-closure dist-tags --registry=https://registry.npmjs.org
curl -s https://registry.npmjs.org/dsh-chip-design-closure/1.13.1 \
  | grep -o '"attestations":{[^}]*}'
```

The last command should report a `provenance` attestation of predicate type
`https://slsa.dev/provenance/v1`; the package page then shows a **Verified**
badge. Registry processing is asynchronous — the new version can take a few
minutes to appear even after the workflow reports success.

## Why `index.js` exists (1.13.3)

A DSH bundle is configuration: the host boots it by reading `dsh.bundle.patch`
out of `package.json` and composing that YAML. Nothing imports the package to
make it work, so `1.13.0`–`1.13.2` shipped with no JavaScript entry at all — 23
files, all YAML/Markdown/Python.

That is legitimate for the host, and it is not for tooling: a reviewer reading
the tarball sees a manifest with no `main`, no `"."` export, and no way to ask
the installed package "where is your patch, which preset do you insert, where do
your skills live" without parsing YAML and reconstructing paths from
`node_modules`.

`1.13.3` adds `index.js`: an ESM module with no side effects that exports
`preset`, `patchPath`, `skillsDir`, `skillName`, plus `readPatch()` and
`describe()`. It is a programmatic door, not a boot requirement.

Verified end to end before publishing:

```sh
npm pack                                  # 24 files, index.js included
npm install ./dsh-chip-design-closure-1.13.3.tgz
node -e "import('dsh-chip-design-closure').then(m => console.log(m.describe()))"
```

The import resolves and reports the preset id, the patch path and the skill
directory from inside `node_modules`.
