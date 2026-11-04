/** Defaults for the plugin row; the loader passes through a plain config object. */

export const DEFAULT_CONFIG = Object.freeze({
  mode: 'auto',
  baseUrl: 'http://127.0.0.1:8000',
  token: '',
  tokenFile: '/etc/witty-service/witty-service.env',
  sidecarPath: '',
  dataDir: '',
  agentName: 'openfuyao-deployer',
  agentId: '',
  requestTimeoutMs: 30_000,
  sidecarStartTimeoutMs: 45_000,
  requireApproval: true,
  panelDeploy: true,
});

/**
 * Merge the profile patch over the defaults. Config is intentionally validated
 * here rather than through a schemastery export: a local plugin directory does
 * not have `@deepseek-ai/schemastery` on its Node resolution path.
 * @param {Record<string, any> | undefined} input
 */
export function resolveConfig(input) {
  const config = { ...DEFAULT_CONFIG, ...(input ?? {}) };
  if (!['auto', 'external', 'sidecar'].includes(config.mode)) {
    throw new Error(`openFuyao: mode must be auto, external, or sidecar (got ${config.mode})`);
  }
  for (const key of ['requestTimeoutMs', 'sidecarStartTimeoutMs']) {
    if (!Number.isFinite(config[key]) || config[key] <= 0) {
      throw new Error(`openFuyao: ${key} must be a positive number`);
    }
  }
  return config;
}
