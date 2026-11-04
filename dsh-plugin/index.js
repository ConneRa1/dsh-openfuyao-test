/**
 * openFuyao deployment plugin for DeepSeek Harness.
 *
 * The plugin owns a small transport layer (external witty-service or a bundled
 * headless sidecar) and exposes the openFuyao orchestration API as tools.
 */

import { createBackend } from './lib/backend.js';
import { resolveConfig } from './lib/config.js';
import { MUTATING_TOOLS, registerTools } from './lib/tools.js';

export const name = 'dsh-openfuyao';
export const inject = ['tools'];

/**
 * @param {any} ctx
 * @param {Record<string, any>} config
 */
export function apply(ctx, config) {
  const resolved = resolveConfig(config);
  const backend = createBackend(ctx, resolved);

  // The sidecar, when used, is a child process owned by this plugin. Stop it
  // when the plugin is unloaded so a profile reload does not leave an orphan.
  // The disposer stays synchronous; the shutdown rejection is reported instead
  // of becoming an unhandled rejection.
  ctx.effect(() => () => {
    backend.dispose().catch((error) => {
      (ctx.logger ?? console).warn?.('openFuyao: sidecar shutdown failed', error);
    });
  });

  ctx.on('tools/pre-execute', async (exec, next) => {
    if (!resolved.requireApproval || !MUTATING_TOOLS.has(exec.name)) {
      return next();
    }
    const detail = safeArguments(exec.arguments);
    return {
      kind: 'ask',
      reason: `openFuyao tool "${exec.name}" changes infrastructure. Arguments: ${detail}`,
      displayReason: {
        en: `Allow openFuyao to run ${exec.name}? It changes a host, cluster, or deployed application.`,
        zh: `允许 openFuyao 执行 ${exec.name}？该操作会修改宿主机、集群或已部署应用。`,
      },
    };
  });

  registerTools(ctx, backend, resolved);
}

/** @param {unknown} args */
function safeArguments(args) {
  try {
    const text = JSON.stringify(args ?? {});
    return text.length > 500 ? `${text.slice(0, 500)}…` : text;
  } catch {
    return '<unserializable>';
  }
}
