/** Config resolution and external-token resolution (no DSH runtime needed). */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';

import { readEnvFileValue, resolveDataDir, resolveExternalToken } from '../lib/backend.js';
import { resolveConfig } from '../lib/config.js';

function tmpFile(contents) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ofu-config-'));
  const file = path.join(dir, 'service.env');
  fs.writeFileSync(file, contents, 'utf8');
  return file;
}

function withEnv(value, run) {
  const before = process.env.AUTH_TOKEN;
  if (value === undefined) delete process.env.AUTH_TOKEN;
  else process.env.AUTH_TOKEN = value;
  try {
    return run();
  } finally {
    if (before === undefined) delete process.env.AUTH_TOKEN;
    else process.env.AUTH_TOKEN = before;
  }
}

test('config defaults are merged with the profile patch', () => {
  const resolved = resolveConfig({ mode: 'sidecar', agentName: 'agent-x' });
  assert.equal(resolved.mode, 'sidecar');
  assert.equal(resolved.agentName, 'agent-x');
  assert.equal(resolved.baseUrl, 'http://127.0.0.1:8000');
  assert.equal(resolved.requireApproval, true);
});

test('an unknown mode or a non-positive timeout is rejected', () => {
  assert.throws(() => resolveConfig({ mode: 'magic' }), /mode must be/);
  assert.throws(() => resolveConfig({ requestTimeoutMs: 0 }), /positive number/);
  assert.throws(() => resolveConfig({ sidecarStartTimeoutMs: Number.NaN }), /positive number/);
});

test('the explicit token wins over the environment and the token file', () => {
  const file = tmpFile('AUTH_TOKEN=from-file\n');
  withEnv('from-env', () => {
    assert.equal(
      resolveExternalToken({ token: 'from-config', tokenFile: file }),
      'from-config',
    );
  });
});

test('the environment wins over the token file', () => {
  const file = tmpFile('AUTH_TOKEN=from-file\n');
  withEnv('from-env', () => {
    assert.equal(resolveExternalToken({ token: '', tokenFile: file }), 'from-env');
  });
});

test('the token file is the last resort and its absence is an error', () => {
  const file = tmpFile('AUTH_TOKEN=from-file\n');
  withEnv(undefined, () => {
    assert.equal(resolveExternalToken({ token: '', tokenFile: file }), 'from-file');
    assert.throws(
      () => resolveExternalToken({ token: '', tokenFile: path.join(file, 'missing') }),
      /AUTH_TOKEN/,
    );
  });
});

test('the sidecar data directory follows the profile, never the shell variable', () => {
  const configured = resolveDataDir({}, { dataDir: '/tmp/explicit' });
  assert.equal(configured, path.resolve('/tmp/explicit'));

  const profileDir = path.join(os.tmpdir(), 'profile-a');
  const ctx = { get: (name) => (name === 'profileContext' ? { dir: profileDir } : undefined) };
  assert.equal(
    resolveDataDir(ctx, {}),
    path.join(profileDir, 'plugin-data', 'openfuyao'),
  );

  // Outside a profile the fallback is the shared home, and an inherited
  // DSH_PROFILE_DIR must not change it.
  const before = process.env.DSH_PROFILE_DIR;
  process.env.DSH_PROFILE_DIR = path.join(os.tmpdir(), 'shell-only');
  try {
    assert.equal(
      resolveDataDir({}, {}),
      path.join(os.homedir(), '.dsh', 'plugin-data', 'openfuyao'),
    );
  } finally {
    if (before === undefined) delete process.env.DSH_PROFILE_DIR;
    else process.env.DSH_PROFILE_DIR = before;
  }
});

test('env-file values survive export, quotes, CRLF and regex metacharacters', () => {
  const file = tmpFile(
    ['# comment', 'export AUTH_TOKEN="quoted"', 'A.C=dot-key', 'PLAIN=bare\r', ''].join('\r\n'),
  );
  assert.equal(readEnvFileValue(file, 'AUTH_TOKEN'), 'quoted');
  assert.equal(readEnvFileValue(file, 'PLAIN'), 'bare');
  assert.equal(readEnvFileValue(file, 'A.C'), 'dot-key');
  assert.equal(readEnvFileValue(file, 'ABC'), '', 'the key must be matched literally');
  assert.equal(readEnvFileValue(path.join(file, 'missing'), 'AUTH_TOKEN'), '');
});
