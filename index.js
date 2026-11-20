/**
 * Entry point for `dsh-chip-design-closure`.
 *
 * A DSH bundle is configuration, not behaviour: what it ships is a Cordis patch
 * plus a skill directory. So this module has no runtime side effects — it
 * exports the *coordinates* of that configuration (patch path, preset id, skill
 * directory) so an installer, a smoke test or a marketplace verifier can resolve
 * the bundle without parsing YAML or guessing where files landed after install.
 *
 * The bundle still loads without importing this file: the host reads
 * `dsh.bundle.patch` from package.json. This is the programmatic door, not a
 * boot requirement.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Directory of the installed package. */
export const root = dirname(fileURLToPath(import.meta.url));

/** The preset this bundle inserts, mirroring the row in cordis.patch.yml. */
export const preset = Object.freeze({
  id: 'chip-arch-expert',
  name: '设计收口',
  order: 20,
});

/** Absolute path to the Cordis patch declared by `dsh.bundle.patch`. */
export const patchPath = join(root, 'cordis.patch.yml');

/** Absolute path to the skill root (one skill lives here: `chip-design`). */
export const skillsDir = join(root, 'skills');

/** Name of the skill this bundle carries. */
export const skillName = 'chip-design';

/** The patch source, for tools that want to inspect it before composing. */
export function readPatch() {
  return readFileSync(patchPath, 'utf8');
}

/** Everything above in one object, for logging and verification. */
export function describe() {
  return { preset, patchPath, skillsDir, skillName };
}

export default describe;
