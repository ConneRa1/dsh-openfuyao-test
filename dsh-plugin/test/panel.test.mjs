/** Host routes: trust fence, method guard, body limits and the deploy gate. */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { registerPanel } from '../lib/panel.js';

/**
 * @param {{rejection?: number|'throw'|'missing'}} [options] — `missing` models a
 * renamed trust fence: the connection service exists but offers no method.
 */
function harness({ rejection } = {}) {
  const routes = new Map();
  let connection;
  if (rejection === 'missing') {
    connection = {};
  } else {
    connection = {
      requestRejection: rejection === 'throw'
        ? () => { throw new Error('trust fence unavailable'); }
        : () => rejection,
    };
  }
  const scope = {
    connection,
    effect: (factory) => factory(),
    webServer: {
      register: (route) => {
        routes.set(route.path, route);
        return () => {};
      },
    },
  };
  const ctx = { inject: (_names, callback) => callback(scope) };
  return { routes, ctx };
}

function request({ method = 'GET', url = '/', body = '' } = {}) {
  return {
    method,
    url,
    headers: {},
    async *[Symbol.asyncIterator]() {
      if (body) yield Buffer.from(body);
    },
  };
}

function response() {
  return {
    statusCode: 200,
    headers: {},
    body: '',
    ended: false,
    setHeader(name, value) {
      this.headers[name.toLowerCase()] = value;
    },
    end(chunk) {
      if (chunk !== undefined) this.body += chunk;
      this.ended = true;
    },
    json() {
      return JSON.parse(this.body);
    },
  };
}

/** Minimal backend: records calls and answers the two overview endpoints. */
function backend() {
  const calls = [];
  return {
    transport: { kind: 'sidecar', baseUrl: 'http://127.0.0.1:9' },
    calls,
    agentId: async () => 'agent-1',
    request: async (method, path) => {
      calls.push(`${method} ${path}`);
      if (path.startsWith('/openfuyao/environments')) return [];
      return { clusters: [], apps: [], issues: [], errors: [], refreshed_at: '2026-01-01T00:00:00Z' };
    },
  };
}

function route(routes, path) {
  const found = routes.get(path);
  assert.ok(found, `route ${path} is not registered`);
  return found.handler;
}

test('a rejected peer never reaches the handler', async () => {
  const { routes, ctx } = harness({ rejection: 403 });
  const client = backend();
  registerPanel(ctx, client, { mode: 'auto', panelDeploy: true });
  const res = response();
  await route(routes, '/openfuyao/api/overview')(request(), res);
  assert.equal(res.statusCode, 403);
  assert.deepEqual(client.calls, []);
});

test('a missing or broken trust fence fails closed', async () => {
  for (const rejection of ['throw', 'missing']) {
    const { routes, ctx } = harness({ rejection });
    const client = backend();
    registerPanel(ctx, client, { mode: 'auto', panelDeploy: true });
    const res = response();
    await route(routes, '/openfuyao/api/overview')(request(), res);
    assert.equal(res.statusCode, 403, `rejection=${rejection} must be refused`);
    assert.equal(res.ended, true);
    assert.deepEqual(client.calls, []);
  }
});

test('the method guard answers 405 with an allow header', async () => {
  const { routes, ctx } = harness();
  registerPanel(ctx, backend(), { mode: 'auto', panelDeploy: true });
  const res = response();
  await route(routes, '/openfuyao/api/overview')(
    request({ method: 'POST' }),
    res,
  );
  assert.equal(res.statusCode, 405);
  assert.equal(res.headers.allow, 'GET');
  assert.equal(res.json().error.code, 'METHOD_NOT_ALLOWED');
});

test('the plan route is a POST', async () => {
  const { routes, ctx } = harness();
  registerPanel(ctx, backend(), { mode: 'auto', panelDeploy: true });
  const res = response();
  await route(routes, '/openfuyao/api/plan')(request({ method: 'POST' }), res);
  assert.equal(res.statusCode, 200);
  assert.equal(res.json().preflight, null);
});

test('overview reports the transport and refuses to leak the token', async () => {
  const { routes, ctx } = harness();
  const client = backend();
  client.token = 'super-secret-token';
  registerPanel(ctx, client, { mode: 'auto', panelDeploy: false });
  const res = response();
  await route(routes, '/openfuyao/api/overview')(request(), res);
  assert.equal(res.statusCode, 200);
  const payload = res.json();
  assert.equal(payload.transport.mode, 'sidecar');
  assert.deepEqual(payload.environments, []);
  assert.deepEqual(payload.errors, []);
  assert.equal(payload.panelDeploy, false);
  assert.doesNotMatch(res.body, /super-secret-token/);
});

test('deploy refuses without an explicit confirmation', async () => {
  const { routes, ctx } = harness();
  const client = backend();
  registerPanel(ctx, client, { mode: 'auto', panelDeploy: true });
  const res = response();
  await route(routes, '/openfuyao/api/deploy')(
    request({ method: 'POST', body: JSON.stringify({ confirm: false }) }),
    res,
  );
  assert.equal(res.statusCode, 400);
  assert.equal(res.json().error.code, 'CONFIRM_REQUIRED');
  assert.deepEqual(client.calls, []);
});

test('deploy is refused when the panel is not allowed to deploy', async () => {
  const { routes, ctx } = harness();
  registerPanel(ctx, backend(), { mode: 'auto', panelDeploy: false });
  const res = response();
  await route(routes, '/openfuyao/api/deploy')(
    request({ method: 'POST', body: JSON.stringify({ confirm: true }) }),
    res,
  );
  assert.equal(res.statusCode, 403);
  assert.equal(res.json().error.code, 'PANEL_DEPLOY_DISABLED');
});

test('oversized and malformed bodies are rejected before the backend', async () => {
  const { routes, ctx } = harness();
  const client = backend();
  registerPanel(ctx, client, { mode: 'auto', panelDeploy: true });

  const tooLarge = response();
  await route(routes, '/openfuyao/api/deploy')(
    request({ method: 'POST', body: JSON.stringify({ pad: 'x'.repeat(70_000) }) }),
    tooLarge,
  );
  assert.equal(tooLarge.statusCode, 413);
  assert.equal(tooLarge.json().error.code, 'BODY_TOO_LARGE');

  const malformed = response();
  await route(routes, '/openfuyao/api/deploy')(
    request({ method: 'POST', body: '{not json' }),
    malformed,
  );
  assert.equal(malformed.statusCode, 400);
  assert.equal(malformed.json().error.code, 'INVALID_JSON');

  assert.deepEqual(client.calls, []);
});

test('cancel rejects an unknown target', async () => {
  const { routes, ctx } = harness();
  const client = backend();
  registerPanel(ctx, client, { mode: 'auto', panelDeploy: true });
  const res = response();
  await route(routes, '/openfuyao/api/cancel')(
    request({ method: 'POST', body: JSON.stringify({ target: 'nope', id: 'x' }) }),
    res,
  );
  assert.equal(res.statusCode, 400);
  assert.equal(res.json().error.code, 'INVALID_CANCEL');
  assert.deepEqual(client.calls, []);
});
