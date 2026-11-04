/**
 * Host-side JSON routes backing the openFuyao right-sidebar panel.
 *
 * The panel runs in the browser and must not talk to the sidecar directly: the
 * sidecar's bearer token is a Host secret and the sidecar binds an ephemeral
 * loopback port. These routes are the only bridge, and they reuse the same
 * Backend instance as the model-facing tools so both surfaces share one
 * transport.
 *
 * Read-only routes:
 *   GET  /openfuyao/api/overview
 *   GET  /openfuyao/api/environments
 *   GET  /openfuyao/api/logs   (tail or cursor-paged bootstrap log)
 *
 * User-initiated routes (the panel asks for explicit confirmation first):
 *   POST /openfuyao/api/plan      (dry-run preflight: it runs host checks)
 *   POST /openfuyao/api/preflight
 *   POST /openfuyao/api/deploy
 *   POST /openfuyao/api/cancel
 */

const OVERVIEW_PATH = '/openfuyao/api/overview';
const PLAN_PATH = '/openfuyao/api/plan';
const ENVIRONMENTS_PATH = '/openfuyao/api/environments';
const LOGS_PATH = '/openfuyao/api/logs';
const PREFLIGHT_PATH = '/openfuyao/api/preflight';
const DEPLOY_PATH = '/openfuyao/api/deploy';
const CANCEL_PATH = '/openfuyao/api/cancel';

const MAX_BODY_BYTES = 64 * 1024;
const ACTIVE_STATUSES = new Set(['bootstrapping', 'waiting_console']);
const LOG_PAGE_BYTES = 1024 * 1024;
const LOG_TAIL_LINES = 300;
const LOG_MAX_PAGES = 16;
const TARGET_PATH = {
  environment: 'environments',
  cluster: 'clusters',
  app: 'apps',
};

/**
 * @param {any} ctx
 * @param {ReturnType<import('./backend.js').createBackend>} backend
 * @param {Record<string, any>} config
 */
export function registerPanel(ctx, backend, config) {
  // `webServer` is absent in headless profiles. Waiting for it through
  // `ctx.inject` keeps this plugin usable as a pure tool bundle there.
  ctx.inject(['webServer', 'connection'], (scope) => {
    const routes = [
      ['GET', OVERVIEW_PATH, (req, res) => handleOverview(backend, config, req, res)],
      ['POST', PLAN_PATH, (req, res) => handlePlan(backend, config, req, res)],
      ['GET', ENVIRONMENTS_PATH, (req, res) => handleEnvironments(backend, config, req, res)],
      ['GET', LOGS_PATH, (req, res) => handleLogs(backend, config, req, res)],
      ['POST', PREFLIGHT_PATH, (req, res) => handlePreflight(backend, config, req, res)],
      ['POST', DEPLOY_PATH, (req, res) => handleDeploy(backend, config, req, res)],
      ['POST', CANCEL_PATH, (req, res) => handleCancel(backend, config, req, res)],
    ];

    for (const [method, path, handler] of routes) {
      scope.effect(() => scope.webServer.register({
        kind: 'exact',
        path,
        handler: guard(scope.connection, method, handler),
      }), `openfuyao: ${method} ${path}`);
    }
  });
}

/**
 * Method check, trust fence, and one JSON error shape for every route.
 *
 * @param {any} connection
 * @param {string} method
 * @param {(req: import('node:http').IncomingMessage, res: import('node:http').ServerResponse) => unknown} handler
 */
function guard(connection, method, handler) {
  return async (req, res) => {
    if (rejectUntrusted(connection, req, res)) return;
    if (req.method !== method) {
      res.setHeader('allow', method);
      sendJson(res, 405, {
        error: { code: 'METHOD_NOT_ALLOWED', message: `${method} only` },
      });
      return;
    }
    try {
      await handler(req, res);
    } catch (error) {
      sendError(res, error);
    }
  };
}

/** @param {any} backend @param {Record<string, any>} config */
function transportInfo(backend, config) {
  return {
    mode: backend.transport?.kind ?? config.mode ?? 'auto',
    baseUrl: backend.transport?.baseUrl ?? null,
  };
}

/**
 * @param {any} backend
 * @param {Record<string, any>} config
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
async function handleOverview(backend, config, req, res) {
  const agentId = await backend.agentId();
  const query = `agent_id=${encodeURIComponent(agentId)}`;
  const [overviewResult, environmentsResult] = await Promise.allSettled([
    backend.request('GET', `/openfuyao/overview?${query}`, { timeoutMs: 120_000 }),
    backend.request('GET', `/openfuyao/environments?${query}`, { timeoutMs: 30_000 }),
  ]);

  const overview = overviewResult.status === 'fulfilled' ? overviewResult.value : null;
  const environments = environmentsResult.status === 'fulfilled' ? environmentsResult.value : null;
  if (overview === null && environments === null) {
    throw overviewResult.status === 'rejected'
      ? overviewResult.reason
      : environmentsResult.reason;
  }

  const failures = [];
  if (overviewResult.status === 'rejected') failures.push(describeFailure(overviewResult.reason));
  if (environmentsResult.status === 'rejected') failures.push(describeFailure(environmentsResult.reason));

  sendJson(res, 200, {
    transport: transportInfo(backend, config),
    refreshedAt: overview?.refreshed_at ?? new Date().toISOString(),
    environments: Array.isArray(environments) ? environments : [],
    clusters: Array.isArray(overview?.clusters) ? overview.clusters : [],
    apps: Array.isArray(overview?.apps) ? overview.apps : [],
    issues: Array.isArray(overview?.issues) ? overview.issues : [],
    errors: [
      ...(Array.isArray(overview?.errors) ? overview.errors : []),
      ...failures,
    ],
    console: overview?.console ?? null,
    guideConsole: overview?.guide_console ?? null,
    discovered: overview?.discovered ?? false,
    // The panel may show a one-click deployment only when the profile allows
    // user-initiated deployment. Model tools stay approval-gated regardless.
    panelDeploy: config.panelDeploy !== false,
  });
}

/**
 * Run the read-only host preflight through the same dry-run endpoint as
 * `openfuyao_plan`. It returns a plan even when no environment exists yet.
 *
 * Exposed as POST, not GET: the upstream call runs host checks (`bke`,
 * `kubectl`, `sudo -n`), and a side-effecting GET can be triggered by a
 * prefetch or a cached link.
 *
 * @param {any} backend
 * @param {Record<string, any>} config
 * @param {import('node:http').IncomingMessage} _req
 * @param {import('node:http').ServerResponse} res
 */
async function handlePlan(backend, config, _req, res) {
  const result = await backend.request('POST', '/openfuyao/environments', {
    timeoutMs: 180_000,
    body: { agent_id: await backend.agentId(), dry_run: true },
  });
  sendPlanResult(res, backend, config, result);
}

/**
 * Lightweight environment list for deployment polling.
 *
 * @param {any} backend
 * @param {Record<string, any>} config
 * @param {import('node:http').IncomingMessage} _req
 * @param {import('node:http').ServerResponse} res
 */
async function handleEnvironments(backend, config, _req, res) {
  const agentId = await backend.agentId();
  const environments = await backend.request(
    'GET',
    `/openfuyao/environments?agent_id=${encodeURIComponent(agentId)}`,
    { timeoutMs: 30_000 },
  );
  sendJson(res, 200, {
    transport: transportInfo(backend, config),
    refreshedAt: new Date().toISOString(),
    environments: Array.isArray(environments) ? environments : [],
  });
}

/**
 * Read the bootstrap log for one environment.
 *
 * `tail=1` walks the byte cursor to the end of the file and returns only the
 * last page of lines, so the panel can show "what is happening now" without
 * downloading the whole log. Without `tail`, the route proxies one cursor page
 * for the 2-second incremental poll. No Python change is needed: this uses the
 * same `/environments/{id}/logs` endpoint as `openfuyao_logs`.
 *
 * @param {any} backend
 * @param {Record<string, any>} config
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
async function handleLogs(backend, config, req, res) {
  const url = new URL(req.url ?? '/', 'http://localhost');
  const environmentId = String(url.searchParams.get('environment_id') ?? '').trim();
  if (!environmentId) {
    throw httpError(400, 'INVALID_LOG_REQUEST', 'environment_id is required');
  }

  if (url.searchParams.get('tail') === '1') {
    const page = await readLogTail(backend, environmentId);
    sendJson(res, 200, {
      transport: transportInfo(backend, config),
      refreshedAt: new Date().toISOString(),
      ...page,
    });
    return;
  }

  const cursor = nonNegativeInt(url.searchParams.get('cursor'), 0);
  const limit = clamp(nonNegativeInt(url.searchParams.get('limit_bytes'), 256 * 1024), 1024, LOG_PAGE_BYTES);
  const page = await backend.request(
    'GET',
    `/openfuyao/environments/${encodeURIComponent(environmentId)}/logs`
      + `?cursor=${cursor}&limit_bytes=${limit}`,
    { timeoutMs: 30_000 },
  );
  sendJson(res, 200, {
    transport: transportInfo(backend, config),
    refreshedAt: new Date().toISOString(),
    cursor: Number(page?.cursor) || cursor,
    next_cursor: Number(page?.next_cursor) || cursor,
    lines: Array.isArray(page?.lines) ? page.lines.map(normalizeLogLine) : [],
    eof: page?.eof !== false,
  });
}

/**
 * @param {any} backend
 * @param {string} environmentId
 */
async function readLogTail(backend, environmentId) {
  let cursor = 0;
  let last = null;
  let lines = [];
  for (let pageNo = 0; pageNo < LOG_MAX_PAGES; pageNo += 1) {
    const page = await backend.request(
      'GET',
      `/openfuyao/environments/${encodeURIComponent(environmentId)}/logs`
        + `?cursor=${cursor}&limit_bytes=${LOG_PAGE_BYTES}`,
      { timeoutMs: 30_000 },
    );
    last = page;
    if (Array.isArray(page?.lines)) {
      lines.push(...page.lines);
      if (lines.length > LOG_TAIL_LINES * 2) lines = lines.slice(-LOG_TAIL_LINES * 2);
    }
    if (page?.eof !== false) break;
    const next = Number(page?.next_cursor);
    if (!Number.isFinite(next) || next <= cursor) break;
    cursor = next;
  }

  const reachedEnd = last?.eof !== false;
  return {
    cursor: Number(last?.cursor) || 0,
    next_cursor: Number(last?.next_cursor) || cursor,
    lines: lines.slice(-LOG_TAIL_LINES).map(normalizeLogLine),
    eof: reachedEnd,
    truncated: !reachedEnd || lines.length > LOG_TAIL_LINES,
  };
}

/** @param {string} value @param {number} fallback */
function nonNegativeInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

/** @param {number} value @param {number} min @param {number} max */
function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

/** @param {unknown} line */
function normalizeLogLine(line) {
  const text = typeof line === 'string' ? line : String(line ?? '');
  return text.length > 2000 ? text.slice(-2000) : text;
}

/**
 * Re-run preflight. With an environment id this updates the stored report; with
 * no id it is the same dry-run as `openfuyao_plan`.
 *
 * @param {any} backend
 * @param {Record<string, any>} config
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
async function handlePreflight(backend, config, req, res) {
  const body = await readJsonBody(req);
  const environmentId = typeof body.environment_id === 'string' ? body.environment_id : '';
  if (!environmentId) {
    const result = await backend.request('POST', '/openfuyao/environments', {
      timeoutMs: 180_000,
      body: { agent_id: await backend.agentId(), dry_run: true },
    });
    sendPlanResult(res, backend, config, result);
    return;
  }

  const environment = await backend.request(
    'POST',
    `/openfuyao/environments/${encodeURIComponent(environmentId)}/preflight`,
    { timeoutMs: 180_000 },
  );
  sendJson(res, 200, {
    transport: transportInfo(backend, config),
    refreshedAt: environment?.updated_at ?? new Date().toISOString(),
    environment,
    preflight: environment?.preflight ?? null,
    plan: [],
  });
}

/**
 * User-initiated deployment: create/reuse the environment record, verify the
 * fresh preflight, then start Bootstrap. `confirm: true` is required; the panel
 * only sends it after the user ticks the confirmation checkbox.
 *
 * @param {any} backend
 * @param {Record<string, any>} config
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
async function handleDeploy(backend, config, req, res) {
  if (config.panelDeploy === false) {
    throw httpError(403, 'PANEL_DEPLOY_DISABLED', 'Panel deployment is disabled; use the openfuyao_deploy tool');
  }
  const body = await readJsonBody(req);
  if (body.confirm !== true) {
    throw httpError(400, 'CONFIRM_REQUIRED', 'Deployment requires confirm=true');
  }

  const prepared = await backend.request('POST', '/openfuyao/environments', {
    timeoutMs: 180_000,
    body: { agent_id: await backend.agentId(), dry_run: false },
  });
  const environment = prepared?.environment;
  const preflight = prepared?.preflight;
  const plan = Array.isArray(prepared?.plan) ? prepared.plan : [];

  if (!environment) {
    throw httpError(502, 'ENVIRONMENT_NOT_CREATED', 'The service did not return an environment');
  }
  if (body.host && preflight?.host && body.host !== preflight.host) {
    throw httpError(409, 'HOST_MISMATCH', 'The panel host no longer matches this host', {
      expected: preflight.host,
      received: body.host,
    });
  }
  if (environment.status === 'ready') {
    sendJson(res, 200, {
      started: false,
      reason: 'already_ready',
      environment,
      preflight,
      plan,
    });
    return;
  }
  if (ACTIVE_STATUSES.has(environment.status)) {
    sendJson(res, 202, {
      started: false,
      reason: 'already_running',
      environment,
      preflight,
      plan,
    });
    return;
  }
  if (!preflight?.ready) {
    sendJson(res, 400, {
      error: {
        code: 'PREFLIGHT_FAILED',
        message: 'Host preflight did not pass; fix the failed checks and retry',
        details: { environment, preflight, plan },
      },
    });
    return;
  }

  const bootstrapped = await backend.request(
    'POST',
    `/openfuyao/environments/${encodeURIComponent(environment.id)}/bootstrap`,
    { timeoutMs: 120_000, body: { confirm: true } },
  );
  sendJson(res, 202, {
    started: true,
    environment: bootstrapped,
    preflight,
    plan,
  });
}

/**
 * Cancel an environment/cluster/app operation. The panel currently sends only
 * `environment`, but the same route covers the other two targets.
 *
 * @param {any} backend
 * @param {Record<string, any>} config
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
async function handleCancel(backend, config, req, res) {
  const body = await readJsonBody(req);
  const target = body.target ?? 'environment';
  const id = body.id;
  if (typeof id !== 'string' || id === '' || !TARGET_PATH[target]) {
    throw httpError(400, 'INVALID_CANCEL', 'cancel requires target and id');
  }
  const environment = await backend.request(
    'POST',
    `/openfuyao/${TARGET_PATH[target]}/${encodeURIComponent(id)}/cancel`,
    { timeoutMs: 60_000 },
  );
  sendJson(res, 200, {
    transport: transportInfo(backend, config),
    refreshedAt: new Date().toISOString(),
    environment,
  });
}

/**
 * Normalize the dry-run/preflight response into the panel's plan shape.
 *
 * @param {import('node:http').ServerResponse} res
 * @param {any} backend
 * @param {Record<string, any>} config
 * @param {any} result
 */
function sendPlanResult(res, backend, config, result) {
  sendJson(res, 200, {
    transport: transportInfo(backend, config),
    refreshedAt: result?.preflight?.checked_at ?? new Date().toISOString(),
    environment: result?.environment ?? null,
    preflight: result?.preflight ?? null,
    plan: Array.isArray(result?.plan) ? result.plan : [],
    created: Boolean(result?.created),
  });
}

/**
 * The Web carrier's own trust fence. The routes are mounted only together with
 * the connection service, so the browser peer is always rejectable.
 *
 * @param {any} connection
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
function rejectUntrusted(connection, req, res) {
  let rejection;
  try {
    // Fail closed in every direction: a missing or renamed trust fence must not
    // expose host state, so it is treated like a rejected request.
    if (typeof connection?.requestRejection !== 'function') {
      throw new Error('connection.requestRejection is unavailable');
    }
    rejection = connection.requestRejection(req);
  } catch {
    res.statusCode = 403;
    res.end();
    return true;
  }
  if (rejection === undefined) return false;
  res.statusCode = rejection;
  res.end();
  return true;
}

/**
 * Read a small JSON request body. The panel only sends ids, flags, and a host,
 * so 64 KiB is far above any legitimate payload.
 *
 * @param {import('node:http').IncomingMessage} req
 * @returns {Promise<Record<string, any>>}
 */
async function readJsonBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) {
      throw httpError(413, 'BODY_TOO_LARGE', 'Request body is too large');
    }
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  let parsed;
  try {
    parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw httpError(400, 'INVALID_JSON', 'Request body is not valid JSON');
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw httpError(400, 'INVALID_JSON', 'Request body must be a JSON object');
  }
  return parsed;
}

/** @param {number} status @param {string} code @param {string} message @param {unknown} [details] */
function httpError(status, code, message, details = null) {
  const error = new Error(message);
  error.status = status;
  error.code = code;
  error.details = details;
  return error;
}

/** @param {unknown} error */
function sendError(res, error) {
  const status = Number(error?.status) || 502;
  sendJson(res, status, {
    error: {
      code: String(error?.code ?? 'OPENFUYAO_PANEL_FAILED'),
      message: String(error?.message ?? error),
      details: error?.details ?? null,
    },
  });
}

/** @param {unknown} error */
function describeFailure(error) {
  const code = error && typeof error === 'object' && 'code' in error
    ? String(error.code)
    : 'OPENFUYAO_PARTIAL_FAILURE';
  const message = error instanceof Error ? error.message : String(error);
  return `${code}: ${message}`;
}

/**
 * @param {import('node:http').ServerResponse} res
 * @param {number} status
 * @param {unknown} body
 */
function sendJson(res, status, body) {
  const text = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader('content-type', 'application/json; charset=utf-8');
  res.setHeader('cache-control', 'no-store');
  res.end(text);
}
