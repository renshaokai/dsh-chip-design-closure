# dsh-chip-design-closure

A DeepSeek Harness bundle that adds the **设计收口 (Design closure)** agent preset: design-side closure for digital chip front-end work — architecture and budgets, design specs, functional-point and acceptance observation point lists, RTL, lint/CDC, synthesis and timing closure, PPA, SoC integration — handing off at the VP list. Carries the **chip-design** skill.

This is the DeepSeek Harness edition of the CodeBuddy expert plugin `chip-arch-expert` v1.13.0 — same author, adapted packaging. The skill content tracks the upstream release; the persona keeps its substance but is rewritten in second person with the character name dropped, and the preset, tool composition, icon and display metadata are DSH-specific.

## Install

`dsh plugin` forwards its arguments to `pnpm` inside the profile directory, so the argument is a package spec — a package name, a directory, a tarball, or a Git URL — not a file.

Install from a local checkout. This links the directory rather than copying it, so edits to the checkout take effect after a restart:

```sh
dsh plugin --profile <profile> add /path/to/dsh-chip-design-closure
```

```powershell
dsh plugin --profile desktop add D:\path\to\dsh-chip-design-closure
```

Or in the Web GUI: **Plugins** → **Add plugin** → pick the package directory.

Then start a new session and choose the **设计收口** preset.

The package is published on npm as `dsh-chip-design-closure`, so the bare name installs from the registry:

```sh
dsh plugin --profile <profile> add dsh-chip-design-closure
```

Use a local checkout path instead when you want the installed bundle to follow the working tree. The engine requirement is `dsh >= 0.2.2-rc.3`.

## What it adds

| Part | Content |
|---|---|
| Agent preset `chip-arch-expert` | Full persona of a digital chip architect: architecture and budgets, design specs written forward or reverse-engineered from RTL, functional-point and acceptance observation point lists, RTL, lint/CDC, synthesis, timing closure, PPA, SoC integration. Hands off at the VP list. |
| Skill `chip-design` | Workflow reference library: architecture budget, eight-chapter spec outline (document control, register/interface contracts, closure traceability), FP/VP generation, RTL checklist, synthesis and timing, PPA, review checklist (66 forward items / 45 reverse items), SoC integration, delivery formats, plus a spec template, an `md2doc.py` converter (docx/PDF with automatic table of contents), `figrender.py` (draw.io / Mermaid / WaveDrom diagrams to SVG/PNG) and `spec_lint.py` (38 mechanical spec checks — duplicate offsets, overlapping bitfields, `lsb > msb`, width overflow, out-of-segment addresses, stray `TBD`, missing mandatory sections — each reported with a line number and section path). |

Tools mounted with the preset: PowerShell/Bash, filesystem read/write and search, background jobs, todo, skill loading, web search, user questions, deliverable declarations, Office documents, and context compaction.

## Requirements

- DeepSeek Harness `>=0.2.2-rc.3` (`engines.dsh`)

The skill directory is resolved relative to the installed package, so the bundle works from npm, a tarball, or a linked checkout without editing the patch.

## Layout

```
package.json        bundle manifest (dsh.bundle.patch)
cordis.patch.yml    preset declaration: persona + tool rows + skill root
locale/en.json      plugin title and description for the Plugins page
locale/zh.json
docs/DETAIL.md      the bundle's detail page
icon.svg            36×36 chip glyph
skills/chip-design  the skill: SKILL.md, references/, templates/, scripts/
```

## Release

Releasing runs in GitHub Actions through npm trusted publishing, so no token, OTP, or web approval is involved.

1. Bump the version and tag that commit with the same version:

   ```sh
   npm version 1.13.2 --no-git-tag-version
   git commit -am "chore: 1.13.2"
   git tag v1.13.2
   git push origin main
   git push origin v1.13.2
   ```

   Push the tag with its own `git push`. `git push --follow-tags` only carries **annotated** tags, so a tag created with plain `git tag` is silently left behind and the workflow never starts.

2. `.github/workflows/publish.yml` runs on the `v*` tag, refuses to continue when the tag and `package.json` disagree, prints the tarball contents, then publishes with provenance.

The repository is bound to the package once, on the package's **Settings → Trusted Publisher** page on npmjs.com, naming this repository and the workflow file `publish.yml`. A manual `workflow_dispatch` run publishes the current manifest version and therefore only succeeds when that version is not already on the registry.

The workflow needs `npm >= 11.5.1`, which the job installs into its own prefix, and `package.json` must declare `repository.url` matching the GitHub repository, otherwise the registry rejects the provenance bundle. [`docs/RELEASE-NOTES.md`](docs/RELEASE-NOTES.md) records the failure signatures and their fixes.

## Differences from the CodeBuddy edition

- `maxTurns: 80` has no DSH equivalent and is not migrated; use the session controls instead.
- The original 512×512 round badge carries 芯片定制 lettering that is unreadable at row size, so the bundle icon is a plain chip glyph.
- CodeBuddy-only fields (`quickPrompts`, `defaultInitPrompt`, `categoryId`, `expertType`) have no DSH counterpart and are dropped.
- The persona body is in second person and carries no personal name, so the preset reads as a role rather than a character.

## License

MIT © 流片之前. See [LICENSE](LICENSE).
