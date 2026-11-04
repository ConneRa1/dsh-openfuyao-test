/** Model-facing tools registered by the openFuyao plugin. */

const JSON_OUTPUT = {
  schema: {},
  render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }],
};

/**
 * Tools that change a host, a cluster, or a deployed application.
 *
 * Keep this list exhaustive: a new tool missing here silently bypasses the
 * approval gate. `test/tools.test.mjs` enumerates the registered tools and
 * fails unless every one is classified as read-only or mutating.
 */
export const MUTATING_TOOLS = new Set([
  'openfuyao_prepare',
  'openfuyao_deploy',
  'openfuyao_cancel',
  'openfuyao_app_install',
  'openfuyao_app_rollback',
  'openfuyao_app_uninstall',
  'openfuyao_cluster_destroy',
]);

const TARGET_PATH = {
  environment: 'environments',
  cluster: 'clusters',
  app: 'apps',
};

/**
 * Compile the small authoring shape used below into raw JSON Schema.
 * `required` is a per-property marker here and becomes a root `required` list.
 * @param {Record<string, any>} spec
 * @returns {Record<string, any>}
 */
function toJsonSchema(spec) {
  if (!spec || typeof spec !== 'object') return {};
  const { required: _required, ...rest } = spec;
  if (rest.type === 'json') return {};
  const schema = { ...rest };
  if (schema.properties && typeof schema.properties === 'object') {
    schema.properties = Object.fromEntries(
      Object.entries(schema.properties).map(([key, value]) => [key, toJsonSchema(value)]),
    );
  }
  if (schema.items) schema.items = toJsonSchema(schema.items);
  return schema;
}

/**
 * Build a registry-ready tool without importing DSH packages. This keeps the
 * bundle loadable from a plain checkout (the profile does not install
 * `@deepseek-ai/dsh-tools` next to every local plugin).
 * @param {Record<string, any>} options
 */
function tool(options) {
  const specs = options.parameters ?? {};
  const properties = Object.fromEntries(
    Object.entries(specs).map(([key, value]) => [key, toJsonSchema(value)]),
  );
  const required = Object.entries(specs)
    .filter(([, value]) => value && value.required === true)
    .map(([key]) => key);
  const definition = {
    name: options.name,
    description: options.description,
    parameters: {
      type: 'object',
      properties,
      ...(required.length > 0 ? { required } : {}),
    },
    output: options.output ?? JSON_OUTPUT,
    execute: options.execute,
  };
  if (options.timeoutMs !== undefined) definition.timeoutMs = options.timeoutMs;
  if (options.isConcurrencySafe) definition.isConcurrencySafe = options.isConcurrencySafe;
  return definition;
}

/**
 * @param {any} ctx
 * @param {ReturnType<import('./backend.js').createBackend>} backend
 * @param {Record<string, any>} config
 */
export function registerTools(ctx, backend, config) {
  const agentQuery = async () =>
    `agent_id=${encodeURIComponent(await backend.agentId())}`;

  const call = (exec, method, pathName, options = {}) =>
    backend.request(method, pathName, {
      signal: exec.signal,
      timeoutMs: options.timeoutMs ?? config.requestTimeoutMs,
      body: options.body,
    });

  const readOnly = () => true;
  const exclusive = () => false;

  /** @param {Record<string, any>} extra */
  const appParameters = (extra = {}) => ({
    cluster: {
      type: 'string',
      required: true,
      description: 'Name of an existing, ready openFuyao business cluster.',
    },
    release_name: {
      type: 'string',
      required: true,
      description: 'Helm release name for the application.',
    },
    namespace: {
      type: 'string',
      description: 'Kubernetes namespace. Defaults to "default".',
    },
    chart: {
      type: 'string',
      description: 'Helm chart reference when installing from a repository.',
    },
    chart_version: {
      type: 'string',
      description: 'Helm chart version.',
    },
    repo_url: {
      type: 'string',
      description: 'Helm repository URL.',
    },
    chart_dir: {
      type: 'string',
      description: 'Server-side path to a local chart directory.',
    },
    image: {
      type: 'string',
      description: 'Optional image override.',
    },
    node_port: {
      type: 'integer',
      description: 'Optional NodePort to expose.',
    },
    ...extra,
  });

  ctx.tools.register(tool({
    name: 'openfuyao_status',
    description:
      'Read the openFuyao overview: environments, BKE clusters, discovered apps, '
      + 'console URL, and current issues. Use this first when the user asks about '
      + 'deployment state; it is read-only and refreshes from the console.',
    parameters: {},
    output: JSON_OUTPUT,
    timeoutMs: 120_000,
    isConcurrencySafe: readOnly,
    execute: async (_args, exec) =>
      call(exec, 'GET', `/openfuyao/overview?${await agentQuery()}`, {
        timeoutMs: 120_000,
      }),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_environments',
    description:
      'List openFuyao environments for the configured agent, including status, '
      + 'phase, progress, preflight result, console URL, and any error code.',
    parameters: {},
    output: JSON_OUTPUT,
    timeoutMs: 60_000,
    isConcurrencySafe: readOnly,
    execute: async (_args, exec) =>
      call(exec, 'GET', `/openfuyao/environments?${await agentQuery()}`),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_plan',
    description:
      'Run the host preflight without creating or changing anything (dry_run). '
      + 'Returns the preflight checks and the deployment plan. Run this before '
      + 'openfuyao_prepare so the user can see whether the host is ready.',
    parameters: {},
    output: JSON_OUTPUT,
    timeoutMs: 180_000,
    isConcurrencySafe: readOnly,
    execute: async (_args, exec) => call(
      exec,
      'POST',
      '/openfuyao/environments',
      {
        timeoutMs: 180_000,
        body: { agent_id: await backend.agentId(), dry_run: true },
      },
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_prepare',
    description:
      'Create (or reuse) the openFuyao environment record for this host after a '
      + 'successful openfuyao_plan. This records the environment but does not '
      + 'start Bootstrap. Returns the environment id needed by openfuyao_deploy.',
    parameters: {},
    output: JSON_OUTPUT,
    timeoutMs: 180_000,
    isConcurrencySafe: exclusive,
    execute: async (_args, exec) => call(
      exec,
      'POST',
      '/openfuyao/environments',
      {
        timeoutMs: 180_000,
        body: { agent_id: await backend.agentId(), dry_run: false },
      },
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_deploy',
    description:
      'Start openFuyao Bootstrap for a prepared environment. This installs BKE '
      + 'and the openFuyao console on the host and is long-running; the call '
      + 'returns as soon as the deployment is accepted. Ask the user before '
      + 'calling it, then use openfuyao_logs or openfuyao_environments to follow '
      + 'progress.',
    parameters: {
      environment_id: {
        type: 'string',
        required: true,
        description: 'Environment id returned by openfuyao_prepare.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 120_000,
    isConcurrencySafe: exclusive,
    execute: async (args, exec) => call(
      exec,
      'POST',
      `/openfuyao/environments/${encodeURIComponent(args.environment_id)}/bootstrap`,
      { body: { confirm: true } },
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_cancel',
    description:
      'Cancel a running environment Bootstrap, cluster operation, or app '
      + 'installation. Use it when the user asks to stop work; it is safe and '
      + 'does not delete resources.',
    parameters: {
      target: {
        type: 'string',
        required: true,
        enum: ['environment', 'cluster', 'app'],
        description: 'Which kind of resource to cancel.',
      },
      id: {
        type: 'string',
        required: true,
        description: 'Environment, cluster, or app id.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 60_000,
    isConcurrencySafe: exclusive,
    execute: async (args, exec) => call(
      exec,
      'POST',
      `/openfuyao/${TARGET_PATH[args.target]}/${encodeURIComponent(args.id)}/cancel`,
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_logs',
    description:
      'Read a page of openFuyao logs for an environment, cluster, or app. '
      + 'The response contains cursor and next_cursor for incremental reads.',
    parameters: {
      target: {
        type: 'string',
        required: true,
        enum: ['environment', 'cluster', 'app'],
        description: 'Which resource owns the log file.',
      },
      id: {
        type: 'string',
        required: true,
        description: 'Environment, cluster, or app id.',
      },
      cursor: {
        type: 'integer',
        description: 'Byte offset from the previous page. Defaults to 0.',
      },
      limit_bytes: {
        type: 'integer',
        description: 'Page size in bytes (1024..1048576). Defaults to 65536.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 60_000,
    isConcurrencySafe: readOnly,
    execute: async (args, exec) => {
      const query = new URLSearchParams();
      if (args.cursor !== undefined) query.set('cursor', String(args.cursor));
      if (args.limit_bytes !== undefined) {
        query.set('limit_bytes', String(args.limit_bytes));
      }
      const suffix = query.size ? `?${query}` : '';
      return call(
        exec,
        'GET',
        `/openfuyao/${TARGET_PATH[args.target]}/${encodeURIComponent(args.id)}/logs${suffix}`,
      );
    },
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_health',
    description:
      'Probe the openFuyao console health for one environment and return the '
      + 'console/proxy URLs and reachability details.',
    parameters: {
      environment_id: {
        type: 'string',
        required: true,
        description: 'Environment id.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 60_000,
    isConcurrencySafe: readOnly,
    execute: async (args, exec) => call(
      exec,
      'POST',
      `/openfuyao/environments/${encodeURIComponent(args.environment_id)}/health`,
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_clusters',
    description:
      'List business clusters managed or discovered by openFuyao, including '
      + 'status, phase, progress, and node summaries.',
    parameters: {},
    output: JSON_OUTPUT,
    timeoutMs: 60_000,
    isConcurrencySafe: readOnly,
    execute: async (_args, exec) =>
      call(exec, 'GET', `/openfuyao/clusters?${await agentQuery()}`),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_console',
    description:
      'Resolve the openFuyao business console URL for a cluster. The console is '
      + 'opened in a browser tab; this plugin does not embed it.',
    parameters: {
      cluster_id: {
        type: 'string',
        required: true,
        description: 'Cluster id.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 60_000,
    isConcurrencySafe: readOnly,
    execute: async (args, exec) => call(
      exec,
      'GET',
      `/openfuyao/clusters/${encodeURIComponent(args.cluster_id)}/console`,
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_apps',
    description:
      'List applications installed through openFuyao, optionally filtered by '
      + 'cluster id.',
    parameters: {
      cluster_id: {
        type: 'string',
        description: 'Optional cluster id filter.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 60_000,
    isConcurrencySafe: readOnly,
    execute: async (args, exec) => {
      const query = new URLSearchParams({ agent_id: await backend.agentId() });
      if (args.cluster_id !== undefined) query.set('cluster_id', args.cluster_id);
      return call(exec, 'GET', `/openfuyao/apps?${query}`);
    },
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_app_preflight',
    description:
      'Check whether an application can be installed on a ready business '
      + 'cluster (chart, namespace, image, ports). Read-only; run before '
      + 'openfuyao_app_install.',
    parameters: appParameters(),
    output: JSON_OUTPUT,
    timeoutMs: 120_000,
    isConcurrencySafe: readOnly,
    execute: async (args, exec) => call(
      exec,
      'POST',
      '/openfuyao/apps/preflight',
      { body: appBody(await backend.agentId(), args, { confirm: false }) },
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_app_install',
    description:
      'Install a Helm application on a ready business cluster through '
      + 'openFuyao. Ask the user before calling it. The call returns when the '
      + 'installation is accepted; use openfuyao_apps and openfuyao_logs to '
      + 'follow progress.',
    parameters: appParameters({
      values: {
        type: 'object',
        additionalProperties: true,
        description: 'Optional Helm values merged into the generated values file.',
      },
      verify_url: {
        type: 'string',
        description: 'Optional URL to probe after the app becomes ready.',
      },
    }),
    output: JSON_OUTPUT,
    timeoutMs: 120_000,
    isConcurrencySafe: exclusive,
    execute: async (args, exec) => call(
      exec,
      'POST',
      '/openfuyao/apps',
      {
        body: appBody(await backend.agentId(), args, {
          confirm: true,
          values: args.values,
          verify_url: args.verify_url,
        }),
      },
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_app_rollback',
    description:
      'Roll back a deployed application to a previous Helm revision. Ask the '
      + 'user before calling it.',
    parameters: {
      app_id: {
        type: 'string',
        required: true,
        description: 'Application id.',
      },
      revision: {
        type: 'integer',
        description: 'Target Helm revision; omit to roll back one revision.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 120_000,
    isConcurrencySafe: exclusive,
    execute: async (args, exec) => {
      const query = new URLSearchParams({ confirm: 'true' });
      if (args.revision !== undefined) query.set('revision', String(args.revision));
      return call(
        exec,
        'POST',
        `/openfuyao/apps/${encodeURIComponent(args.app_id)}/rollback?${query}`,
      );
    },
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_app_uninstall',
    description:
      'Uninstall an application (delete its Helm release). Ask the user before '
      + 'calling it; this removes the running workload.',
    parameters: {
      app_id: {
        type: 'string',
        required: true,
        description: 'Application id.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 120_000,
    isConcurrencySafe: exclusive,
    execute: async (args, exec) => call(
      exec,
      'DELETE',
      `/openfuyao/apps/${encodeURIComponent(args.app_id)}?confirm=true`,
    ),
  }));

  ctx.tools.register(tool({
    name: 'openfuyao_cluster_destroy',
    description:
      'Delete a business cluster CR through openFuyao. Ask the user before '
      + 'calling it. Node cleanup is reported separately; the plugin never runs '
      + 'kubectl directly to bypass the service state machine.',
    parameters: {
      cluster_id: {
        type: 'string',
        required: true,
        description: 'Cluster id.',
      },
    },
    output: JSON_OUTPUT,
    timeoutMs: 120_000,
    isConcurrencySafe: exclusive,
    execute: async (args, exec) => call(
      exec,
      'DELETE',
      `/openfuyao/clusters/${encodeURIComponent(args.cluster_id)}?confirm=true`,
    ),
  }));
}

/**
 * @param {string} agentId
 * @param {Record<string, any>} args
 * @param {{confirm: boolean, values?: object, verify_url?: string}} options
 */
function appBody(agentId, args, options) {
  const body = {
    agent_id: agentId,
    cluster: args.cluster,
    release_name: args.release_name,
    confirm: options.confirm,
  };
  for (const key of [
    'namespace',
    'chart',
    'chart_version',
    'repo_url',
    'chart_dir',
    'image',
    'node_port',
  ]) {
    if (args[key] !== undefined) body[key] = args[key];
  }
  if (options.values !== undefined) body.values = options.values;
  if (options.verify_url !== undefined) body.verify_url = options.verify_url;
  return body;
}
