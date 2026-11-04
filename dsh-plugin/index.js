/**
 * openFuyao deployment plugin for DeepSeek Harness.
 *
 * The plugin owns a small transport layer: it talks to an external
 * witty-service over HTTP, or spawns the bundled headless sidecar when there is
 * none. The openFuyao orchestration API is exposed on top of that transport.
 */

import { createBackend } from './lib/backend.js';
import { resolveConfig } from './lib/config.js';

export const name = 'dsh-openfuyao';

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
}
