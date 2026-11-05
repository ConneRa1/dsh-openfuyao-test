#!/usr/bin/env node
/**
 * Stage one prebuilt sidecar into an npm platform package.
 *
 * The sidecar is ~70 MB and architecture specific, so it cannot live inside
 * `@mlt_123/dsh-openfuyao-test` itself: one version of an npm package can only be
 * published once, and two architectures would collide. Each build instead
 * produces its own package, and the `os` / `cpu` fields make npm install only
 * the one that matches the host.
 *
 * Usage:
 *   node scripts/make-sidecar-package.mjs \
 *     --dist build/sidecar-dist/witty-openfuyao-sidecar \
 *     --platform linux-arm64 \
 *     --version 1.0.0 \
 *     --out build/npm/linux-arm64
 *
 * The package deliberately declares no `dsh` field and no `exports`:
 *   - a `dsh.bundle` field would make DSH mount it as a plugin row;
 *   - an `exports` map would reject the `require.resolve('<pkg>/package.json')`
 *     the Host uses to locate the binary.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Keep in sync with PLATFORM_PACKAGES in dsh-plugin/lib/backend.js. */
const PLATFORMS = {
  'linux-x64': { os: 'linux', cpu: 'x64', suffix: 'linux-x64' },
  'linux-arm64': { os: 'linux', cpu: 'arm64', suffix: 'linux-arm64' },
};

const BINARY_NAME = 'witty-openfuyao-sidecar';

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function parseArgs(argv) {
  /** @type {Record<string, string>} */
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) fail(`无法识别的参数：${token}`);
    const value = argv[index + 1];
    if (value === undefined || value.startsWith('--')) fail(`${token} 缺少取值`);
    args[token.slice(2)] = value;
    index += 1;
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));

for (const required of ['dist', 'platform', 'version', 'out']) {
  if (!args[required]) fail(`缺少 --${required}`);
}

const platform = PLATFORMS[args.platform];
if (!platform) {
  fail(`不支持的平台：${args.platform}（可选：${Object.keys(PLATFORMS).join(', ')}）`);
}

if (!/^\d+\.\d+\.\d+$/.test(args.version)) {
  fail(`版本号不是合法的 SemVer：${args.version}`);
}

const distDir = path.resolve(ROOT, args.dist);
const outDir = path.resolve(ROOT, args.out);
const builtBinary = path.join(distDir, BINARY_NAME);

if (!fs.existsSync(builtBinary)) {
  fail(`找不到构建产物：${builtBinary}\n先运行 ./scripts/build-sidecar.sh`);
}

// `_internal/` must stay next to the executable: the onedir layout resolves it
// relative to the binary, so the pair has to be copied together.
fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(outDir, { recursive: true });
fs.cpSync(distDir, path.join(outDir, 'sidecar'), { recursive: true });

const stagedBinary = path.join(outDir, 'sidecar', BINARY_NAME);
fs.chmodSync(stagedBinary, 0o755);

const name = `@mlt_123/dsh-openfuyao-sidecar-${platform.suffix}-test`;
const manifest = {
  name,
  version: args.version,
  description: `Prebuilt openFuyao sidecar for ${platform.os}/${platform.cpu}, used by @mlt_123/dsh-openfuyao-test.`,
  license: 'MIT',
  os: [platform.os],
  cpu: [platform.cpu],
  repository: {
    type: 'git',
    url: 'git+https://github.com/openwitty/witty-service.git',
    directory: 'dsh-plugin',
  },
  publishConfig: { access: 'public' },
  files: ['sidecar/**'],
};

fs.writeFileSync(
  path.join(outDir, 'package.json'),
  `${JSON.stringify(manifest, null, 2)}\n`,
  'utf8',
);

process.stderr.write(
  `平台包：${name}@${args.version}\n`
    + `目录：${path.relative(ROOT, outDir)}\n`
    + `入口：sidecar/${BINARY_NAME}（可执行位已设置）\n`,
);

process.stdout.write(`${name}\n`);
