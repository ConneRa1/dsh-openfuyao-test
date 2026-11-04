/** Tool-surface contract: names, approval classification, JSON Schema shape. */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MUTATING_TOOLS, registerTools } from '../lib/tools.js';

/**
 * Tools the model may call without an approval prompt. Listing them explicitly
 * is the point: adding a tool without a decision fails the first test.
 */
const READ_ONLY_TOOLS = new Set([
  'openfuyao_status',
  'openfuyao_environments',
  'openfuyao_plan',
  'openfuyao_logs',
  'openfuyao_health',
  'openfuyao_clusters',
  'openfuyao_console',
  'openfuyao_apps',
  'openfuyao_app_preflight',
]);

function registeredTools() {
  const registered = [];
  const ctx = { tools: { register: (definition) => registered.push(definition) } };
  const backend = {
    agentId: async () => 'agent-1',
    request: async () => ({}),
  };
  registerTools(ctx, backend, { requestTimeoutMs: 30_000 });
  return registered;
}

test('every registered tool is classified as mutating or read-only', () => {
  const names = registeredTools().map((tool) => tool.name);
  assert.equal(names.length, 16, 'update READ_ONLY_TOOLS/MUTATING_TOOLS for a new tool');
  const unclassified = names.filter(
    (name) => !MUTATING_TOOLS.has(name) && !READ_ONLY_TOOLS.has(name),
  );
  assert.deepEqual(unclassified, [], 'classify the new tool so approvals are not skipped');
});

test('the approval set names only registered tools', () => {
  const names = new Set(registeredTools().map((tool) => tool.name));
  const stale = [...MUTATING_TOOLS].filter((name) => !names.has(name));
  assert.deepEqual(stale, [], 'MUTATING_TOOLS references a tool that is not registered');
});

test('tools that change state require approval', () => {
  for (const name of [
    'openfuyao_prepare',
    'openfuyao_deploy',
    'openfuyao_cancel',
    'openfuyao_app_install',
    'openfuyao_app_rollback',
    'openfuyao_app_uninstall',
    'openfuyao_cluster_destroy',
  ]) {
    assert.ok(MUTATING_TOOLS.has(name), `${name} must be approval-gated`);
  }
});

test('every tool declares an object schema, an output and an executor', () => {
  for (const tool of registeredTools()) {
    assert.match(tool.name, /^openfuyao_/, `${tool.name} must keep the shared prefix`);
    assert.equal(tool.parameters.type, 'object', `${tool.name} parameters must be an object`);
    assert.equal(typeof tool.execute, 'function', `${tool.name} has no executor`);
    assert.equal(typeof tool.output?.render, 'function', `${tool.name} has no renderer`);
    assert.ok(tool.output?.schema && typeof tool.output.schema === 'object');
  }
});

test('only true opts a tool into concurrent execution', () => {
  for (const tool of registeredTools()) {
    if (typeof tool.isConcurrencySafe !== 'function') continue;
    assert.equal(typeof tool.isConcurrencySafe({}), 'boolean', `${tool.name} classifier`);
  }
});
