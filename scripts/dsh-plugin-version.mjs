#!/usr/bin/env node
/**
 * Version axis for the DSH openFuyao plugin bundle.
 *
 * The repository publishes two independent release units:
 *
 *   witty-service        tag `v<version>`              PyPI + GHCR
 *   DSH openFuyao plugin tag `dsh-openfuyao-v<version>` npm
 *
 * Only commits that touch `dsh-plugin/` participate in the plugin bump. Without
 * that path scope, a `feat:` for the Python service would silently bump the
 * plugin too, and the panel would ship a version number that describes code it
 * does not contain.
 *
 * Usage:
 *   node scripts/dsh-plugin-version.mjs print
 *   node scripts/dsh-plugin-version.mjs set 1.2.3
 *
 * `print` writes the next version, or `none` when nothing in `dsh-plugin/`
 * warrants a release. `set` writes a version into the three manifests that must
 * always agree: the Host package, the panel package, and the exact pins on the
 * two platform packages.
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TAG_PREFIX = 'dsh-openfuyao-v';
const PACKAGE_DIR = 'dsh-plugin';
const HOST_MANIFEST = path.join(ROOT, PACKAGE_DIR, 'package.json');
const PANEL_MANIFEST = path.join(ROOT, PACKAGE_DIR, 'panel', 'package.json');
const SIDECAR_PACKAGES = [
  '@mlt_123/dsh-openfuyao-sidecar-linux-x64-test',
  '@mlt_123/dsh-openfuyao-sidecar-linux-arm64-test',
];

const BUMP_RANK = { none: 0, patch: 1, minor: 2, major: 3 };

function git(...args) {
  // stderr is dropped so a missing tag does not print git's localised
  // "cannot describe anything" banner into the CI log.
  return execFileSync('git', args, {
    cwd: ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
}

/** @returns {string|null} */
function lastTag() {
  try {
    return git('describe', '--tags', '--abbrev=0', '--match', `${TAG_PREFIX}*`);
  } catch {
    return null;
  }
}

/** @param {string} version */
function parseVersion(version) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(version);
  if (!match) throw new Error(`不是合法的 SemVer：${version}`);
  return match.slice(1).map(Number);
}

/** @param {string} version @param {string} bump */
function bumpVersion(version, bump) {
  let [major, minor, patch] = parseVersion(version);
  if (bump === 'major') {
    major += 1;
    minor = 0;
    patch = 0;
  } else if (bump === 'minor') {
    minor += 1;
    patch = 0;
  } else if (bump === 'patch') {
    patch += 1;
  }
  return `${major}.${minor}.${patch}`;
}

/**
 * Conventional-commit bump for one commit subject plus its body.
 *
 * @param {string} subject
 * @param {string} body
 * @returns {'major'|'minor'|'patch'|'none'}
 */
function classify(subject, body) {
  if (/(^|\n)BREAKING[ -]CHANGE:/.test(body)) return 'major';

  const match = /^([a-zA-Z]+)(?:\([^)]*\))?(!)?:/.exec(subject);
  if (!match) return 'none';
  if (match[2] === '!') return 'major';

  const type = match[1].toLowerCase();
  if (type === 'feat') return 'minor';
  if (type === 'fix' || type === 'perf' || type === 'refactor') return 'patch';
  return 'none';
}

/**
 * Walk the commits since the last plugin tag, scoped to `dsh-plugin/`.
 *
 * @returns {{tag: string|null, base: string, bump: string, commits: {subject: string, type: string}[]}}
 */
function analyse() {
  const tag = lastTag();
  const base = tag ? tag.slice(TAG_PREFIX.length) : '0.0.0';
  const range = tag ? `${tag}..HEAD` : 'HEAD';

  // %x00 separates subject from body, %x01 separates commits: subjects can
  // contain neither, so the split survives multi-line bodies.
  const raw = execFileSync(
    'git',
    ['log', '--format=%s%x00%b%x01', range, '--', PACKAGE_DIR],
    { cwd: ROOT, encoding: 'utf8' },
  );

  const commits = raw
    .split('\x01')
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => {
      const [subject, body = ''] = chunk.split('\x00');
      return { subject: subject.trim(), type: classify(subject.trim(), body) };
    });

  let bump = 'none';
  for (const commit of commits) {
    if (BUMP_RANK[commit.type] > BUMP_RANK[bump]) bump = commit.type;
  }
  return { tag, base, bump, commits };
}

/** @param {string} file @param {(manifest: any) => void} mutate */
function updateManifest(file, mutate) {
  const manifest = JSON.parse(fs.readFileSync(file, 'utf8'));
  mutate(manifest);
  fs.writeFileSync(file, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  return manifest;
}

/** @param {string} version */
function apply(version) {
  parseVersion(version);

  updateManifest(HOST_MANIFEST, (manifest) => {
    manifest.version = version;
    // Exact pins, not ranges: the Host and the binary speak a protocol whose
    // version must match exactly (SIDECAR_API_VERSION), so a ranged optional
    // dependency could quietly resolve to an incompatible build.
    manifest.optionalDependencies ??= {};
    for (const name of SIDECAR_PACKAGES) manifest.optionalDependencies[name] = version;
  });

  updateManifest(PANEL_MANIFEST, (manifest) => {
    manifest.version = version;
  });

  process.stdout.write(`${version}\n`);
}

function main(argv) {
  const [command, argument] = argv;

  if (command === 'print') {
    const { tag, base, bump, commits } = analyse();
    const relevant = commits.filter((commit) => commit.type !== 'none');
    // Diagnostics go to stderr so stdout stays a single machine-readable token.
    process.stderr.write(
      `基线：${tag ?? '(无 tag，按 0.0.0 计)'}\n`
        + `dsh-plugin/ 下自基线以来 ${commits.length} 个提交，其中 ${relevant.length} 个影响版本：\n`
        + relevant.map((commit) => `  ${commit.type.padEnd(5)} ${commit.subject}`).join('\n')
        + '\n',
    );
    process.stdout.write(bump === 'none' ? 'none\n' : `${bumpVersion(base, bump)}\n`);
    return;
  }

  if (command === 'set') {
    if (!argument) throw new Error('用法：dsh-plugin-version.mjs set <version>');
    apply(argument);
    return;
  }

  throw new Error('用法：dsh-plugin-version.mjs <print|set> [version]');
}

try {
  main(process.argv.slice(2));
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
}
