/**
 * Backend connection for the openFuyao DSH plugin.
 *
 * Two transports share one interface:
 *   - external: an already-running witty-service on 127.0.0.1:8000
 *   - sidecar:  the standalone binary bundled with this plugin
 *
 * `auto` probes the external backend first and falls back to the sidecar only
 * when the external process is not listening. A 401/403, a version mismatch, or
 * a server-side error never falls back: starting a second orchestrator against
 * the same database would create two writers.
 */

import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';

import {
  OpenFuyaoError,
  describeError,
  isConnectionError,
  isTimeoutError,
} from './errors.js';

const SIDECAR_API_VERSION = 1;
const DEFAULT_AGENT_NAME = 'openfuyao-deployer';
const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';
const DEFAULT_TOKEN_FILE = '/etc/witty-service/witty-service.env';
const DEFAULT_BINARY = fileURLToPath(
  new URL('../sidecar/witty-openfuyao-sidecar', import.meta.url),
);

/**
 * Prebuilt binaries are published as their own platform packages and pulled in
 * through `optionalDependencies`; their `os`/`cpu` fields make the package
 * manager install only the one that matches the host. Keep this table in sync
 * with `scripts/make-sidecar-package.mjs`.
 */
const PLATFORM_PACKAGES = {
  'linux-x64': '@mlt_123/dsh-openfuyao-sidecar-linux-x64-test',
  'linux-arm64': '@mlt_123/dsh-openfuyao-sidecar-linux-arm64-test',
};

const nodeRequire = createRequire(import.meta.url);

/**
 * @param {import('@deepseek-ai/cordis').Context} ctx
 * @param {Record<string, any>} config
 */
export function createBackend(ctx, config) {
  return new Backend(ctx, config);
}

class Backend {
  /**
   * @param {any} ctx
   * @param {Record<string, any>} config
   */
  constructor(ctx, config) {
    this.ctx = ctx;
    this.config = config;
    this.transport = null;
    this.connectPromise = null;
    this.agent = null;
    this.child = null;
    this.sidecarInfo = null;
    this.stopping = false;
    this.lastStderr = '';
  }

  get log() {
    return this.ctx?.logger ?? console;
  }

  /** Resolve the transport, starting the sidecar if needed. */
  async ensure() {
    if (this.transport) return this.transport;
    if (!this.connectPromise) {
      this.connectPromise = this.#connect().finally(() => {
        this.connectPromise = null;
      });
    }
    return this.connectPromise;
  }

  /**
   * @param {string} method
   * @param {string} pathName
   * @param {{body?: unknown, timeoutMs?: number, signal?: AbortSignal}} [options]
   */
  async request(method, pathName, options = {}) {
    const transport = await this.ensure();
    return this.#fetchJson(
      transport,
      method,
      pathName,
      options.body,
      options.timeoutMs ?? this.config.requestTimeoutMs ?? 30_000,
      options.signal,
    );
  }

  /**
   * Resolve the agent id used by every openFuyao request.
   *
   * The original backend identifies agents by UUID, while the sidecar accepts a
   * stable pseudo-id on a fresh database. External deployments resolve the
   * configured agent name through `GET /agents`.
   */
  async agentId() {
    await this.ensure();
    if (this.agent) return this.agent;

    const configured = String(this.config.agentId ?? '').trim();
    if (configured) {
      this.agent = configured;
      return this.agent;
    }

    const agentName = String(this.config.agentName ?? DEFAULT_AGENT_NAME).trim()
      || DEFAULT_AGENT_NAME;

    if (this.transport?.kind === 'sidecar') {
      this.agent = agentName;
      return this.agent;
    }

    const agents = await this.request('GET', '/agents');
    if (!Array.isArray(agents)) {
      throw new OpenFuyaoError(
        '外部后端的 /agents 返回值不是列表，无法解析 Agent ID',
        { code: 'AGENT_LOOKUP_FAILED' },
      );
    }
    const found = agents.find((item) => item && item.name === agentName);
    if (!found?.id) {
      throw new OpenFuyaoError(
        `外部后端中找不到名为 ${agentName} 的 Agent；请先创建该 Agent，或在插件配置里设置 agentId`,
        { code: 'AGENT_NOT_FOUND' },
      );
    }
    this.agent = found.id;
    return this.agent;
  }

  async dispose() {
    await this.stop();
  }

  async stop() {
    this.stopping = true;
    // A sidecar start may still be in flight. Wait for it so the child exists
    // before the transport is cleared, otherwise the start completes after
    // shutdown and leaves an orphan process pointing at a dead transport.
    await this.connectPromise?.catch(() => {});
    const child = this.child;
    this.child = null;
    this.transport = null;
    this.sidecarInfo = null;
    if (!child || child.exitCode !== null) return;

    await new Promise((resolve) => {
      const timer = setTimeout(() => {
        if (child.exitCode === null) child.kill('SIGKILL');
        resolve();
      }, 5_000);
      child.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
      child.kill('SIGTERM');
    });
  }

  async #connect() {
    const mode = this.config.mode ?? 'auto';
    if (mode === 'external') {
      const transport = await this.#probeExternal(false);
      this.transport = transport;
      return transport;
    }
    if (mode === 'sidecar') {
      return this.#startSidecar();
    }

    const external = await this.#probeExternal(true);
    if (external) {
      this.transport = external;
      return external;
    }
    this.log.warn(
      'openFuyao: 外部后端不可达，启动插件内置 sidecar（独立数据库）',
    );
    return this.#startSidecar();
  }

  /**
   * @param {boolean} allowFallback
   * @returns {Promise<{kind: 'external', baseUrl: string, token: string} | null>}
   */
  async #probeExternal(allowFallback) {
    const baseUrl = String(this.config.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, '');
    let response;
    try {
      response = await fetch(`${baseUrl}/healthz`, {
        signal: AbortSignal.timeout(2_000),
      });
    } catch (error) {
      if (allowFallback && isConnectionError(error)) return null;
      throw new OpenFuyaoError(
        `无法连接外部后端 ${baseUrl}：${describeError(error)}`,
        { code: 'EXTERNAL_UNREACHABLE', cause: error },
      );
    }
    if (!response.ok) {
      throw new OpenFuyaoError(
        `外部后端 ${baseUrl}/healthz 返回 HTTP ${response.status}`,
        { code: 'EXTERNAL_UNHEALTHY', status: response.status },
      );
    }

    const token = resolveExternalToken(this.config);
    const transport = { kind: 'external', baseUrl, token };
    try {
      // A reachable process is not necessarily an openFuyao-capable backend.
      await this.#fetchJson(transport, 'GET', '/openfuyao/environments', undefined, 5_000);
    } catch (error) {
      if (error instanceof OpenFuyaoError && error.status === 401) {
        throw new OpenFuyaoError(
          '外部后端鉴权失败：检查 token/tokenFile（AUTH_TOKEN）',
          { code: 'AUTH_FAILED', status: 401, cause: error },
        );
      }
      if (error instanceof OpenFuyaoError && error.status === 404) {
        throw new OpenFuyaoError(
          '外部后端没有 openFuyao API（版本过旧？）；不会自动启动 sidecar，避免双写',
          { code: 'API_UNAVAILABLE', status: 404, cause: error },
        );
      }
      throw error;
    }

    this.log.info(`openFuyao: 使用外部后端 ${baseUrl}`);
    return transport;
  }

  async #startSidecar() {
    const binary = this.#resolveBinary();
    const dataDir = this.#resolveDataDir();
    fs.mkdirSync(dataDir, { recursive: true, mode: 0o700 });

    const token = randomBytes(32).toString('hex');
    const agentName = String(this.config.agentName ?? DEFAULT_AGENT_NAME).trim()
      || DEFAULT_AGENT_NAME;
    const args = [
      '--host',
      '127.0.0.1',
      '--port',
      '0',
      '--db-path',
      path.join(dataDir, 'sidecar.sqlite3'),
      '--workspace',
      path.join(dataDir, 'workspace'),
      '--parent-pid',
      String(process.pid),
      '--agent-id',
      String(this.config.agentId ?? '').trim() || agentName,
    ];

    this.log.info(`openFuyao: 启动 sidecar ${binary}`);
    const child = spawn(binary, args, {
      cwd: dataDir,
      env: {
        ...process.env,
        // The token travels through the environment, not argv, so it does not
        // appear in `ps` output on a shared host.
        WITTY_SIDECAR_TOKEN: token,
        WITTY_SIDECAR_LOG_LEVEL:
          process.env.WITTY_SIDECAR_LOG_LEVEL ?? 'INFO',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    this.child = child;
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk) => {
      this.lastStderr = (this.lastStderr + chunk).slice(-8_192);
    });

    let ready;
    try {
      ready = await this.#waitForReady(child);
    } catch (error) {
      child.kill('SIGKILL');
      this.child = null;
      throw error;
    }

    const transport = { kind: 'sidecar', baseUrl: ready.url, token };
    try {
      const info = await this.#fetchJson(transport, 'GET', '/sidecar/info', undefined, 5_000);
      if (info?.sidecar !== SIDECAR_API_VERSION) {
        throw new OpenFuyaoError(
          `sidecar 协议版本不匹配：期望 ${SIDECAR_API_VERSION}，实际 ${info?.sidecar}`,
          { code: 'SIDECAR_VERSION_MISMATCH' },
        );
      }
      this.sidecarInfo = info;
    } catch (error) {
      child.kill('SIGKILL');
      this.child = null;
      throw error;
    }

    child.once('exit', (code, signal) => {
      if (this.stopping) return;
      this.log.warn(
        `openFuyao sidecar 退出（code=${code}, signal=${signal}）`,
      );
      if (this.lastStderr.trim()) this.log.warn(this.lastStderr.trim());
      if (this.transport?.kind === 'sidecar') this.transport = null;
      if (this.child === child) this.child = null;
      this.sidecarInfo = null;
    });

    this.transport = transport;
    this.log.info(
      `openFuyao: 使用内置 sidecar ${ready.url}（pid=${ready.pid}）`,
    );
    return transport;
  }

  /** @param {import('node:child_process').ChildProcess} child */
  async #waitForReady(child) {
    const timeoutMs = this.config.sidecarStartTimeoutMs ?? 45_000;
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => {
        fail(new OpenFuyaoError(
          `openFuyao sidecar 在 ${timeoutMs}ms 内未就绪`,
          { code: 'SIDECAR_START_TIMEOUT' },
        ));
      }, timeoutMs);
      const reader = readline.createInterface({ input: child.stdout });

      const cleanup = () => {
        clearTimeout(timer);
        reader.close();
      };
      const fail = (error) => {
        if (settled) return;
        settled = true;
        cleanup();
        const detail = this.lastStderr.trim();
        reject(new OpenFuyaoError(
          detail ? `${error.message}\n${detail}` : error.message,
          { code: error.code ?? 'SIDECAR_START_FAILED', cause: error },
        ));
      };

      reader.on('line', (line) => {
        let message;
        try {
          message = JSON.parse(line);
        } catch {
          return;
        }
        if (message?.event !== 'ready') return;
        settled = true;
        cleanup();
        resolve(message);
      });
      child.once('error', (error) => {
        fail(new OpenFuyaoError(
          `无法启动 openFuyao sidecar：${describeError(error)}`,
          { code: 'SIDECAR_SPAWN_FAILED', cause: error },
        ));
      });
      child.once('exit', (code, signal) => {
        fail(new OpenFuyaoError(
          `openFuyao sidecar 启动时退出（code=${code}, signal=${signal}）`,
          { code: 'SIDECAR_EXITED' },
        ));
      });
    });
  }

  /**
   * Locate the sidecar executable.
   *
   * Resolution order:
   *   1. `sidecarPath` — an explicit override always wins and is the only
   *      candidate probed, so a typo fails loudly instead of silently using
   *      another binary.
   *   2. `<package>/sidecar/witty-openfuyao-sidecar` — a repository checkout
   *      after `scripts/build-sidecar.sh`, and the self-contained tarball
   *      distribution, which ships the binary inside the package.
   *   3. the platform package installed through `optionalDependencies` — what a
   *      plain `dsh plugin add @mlt_123/dsh-openfuyao-test` produces.
   */
  #resolveBinary() {
    const attempts = this.#sidecarCandidates();
    let invalid = null;

    for (const candidate of attempts) {
      let stat;
      try {
        stat = fs.statSync(candidate);
      } catch {
        continue;
      }
      if (!stat.isFile()) {
        invalid ??= {
          candidate,
          code: 'SIDECAR_BINARY_INVALID',
          message: `sidecar 路径不是文件：${candidate}`,
        };
        continue;
      }
      if (!this.#ensureExecutable(candidate)) {
        invalid ??= {
          candidate,
          code: 'SIDECAR_BINARY_NOT_EXECUTABLE',
          message: `sidecar 没有可执行权限：${candidate}`,
        };
        continue;
      }
      return candidate;
    }

    if (invalid) {
      throw new OpenFuyaoError(invalid.message, {
        code: invalid.code,
        details: { attempts, candidate: invalid.candidate },
      });
    }

    const hint = PLATFORM_PACKAGES[`${process.platform}-${process.arch}`];
    throw new OpenFuyaoError(
      '找不到 openFuyao sidecar 可执行文件。\n'
        + `平台：${process.platform}/${process.arch}\n`
        + `已尝试：\n${attempts.map((item) => `  - ${item}`).join('\n')}\n`
        + '处理方式（三选一）：\n'
        + '  - 在仓库中运行 scripts/build-sidecar.sh，或设置 config.sidecarPath\n'
        + (hint
          ? `  - 安装对应平台包：dsh plugin --profile <profile> add ${hint}@<version>\n`
          : '  - 该平台暂无预编译二进制，请自行构建后用 config.sidecarPath 指向它\n')
        + '  - 改为 mode: external，连接已在运行的 witty-service',
      { code: 'SIDECAR_BINARY_MISSING', details: { attempts } },
    );
  }

  /**
   * @returns {string[]} candidates, in the order they should be probed.
   */
  #sidecarCandidates() {
    const configured = String(this.config.sidecarPath ?? '').trim();
    if (configured) return [path.resolve(configured)];

    const candidates = [DEFAULT_BINARY];
    const fromPackage = this.#platformPackageBinary();
    if (fromPackage) candidates.push(fromPackage);
    return candidates;
  }

  /**
   * Resolve the binary out of the platform package, if one is installed for
   * this host. Missing optional dependencies are not an error here: the caller
   * reports every probed path at once.
   *
   * @returns {string|null}
   */
  #platformPackageBinary() {
    const name = PLATFORM_PACKAGES[`${process.platform}-${process.arch}`];
    if (!name) return null;
    try {
      // Requires the platform package to stay exports-free; a subpath export
      // map would reject `./package.json` here.
      const manifest = nodeRequire.resolve(`${name}/package.json`);
      return path.join(path.dirname(manifest), 'sidecar', 'witty-openfuyao-sidecar');
    } catch {
      return null;
    }
  }

  /**
   * npm has been known to drop the execute bit when a tarball passes through a
   * proxy or a store, so try to repair it once before declaring the binary
   * unusable.
   *
   * @param {string} candidate
   * @returns {boolean}
   */
  #ensureExecutable(candidate) {
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      return true;
    } catch {
      // fall through to the repair attempt
    }
    try {
      fs.chmodSync(candidate, 0o755);
      fs.accessSync(candidate, fs.constants.X_OK);
      return true;
    } catch {
      return false;
    }
  }

  #resolveDataDir() {
    return resolveDataDir(this.ctx, this.config);
  }

  /**
   * @param {{baseUrl: string, token: string}} transport
   * @param {string} method
   * @param {string} pathName
   * @param {unknown} body
   * @param {number} timeoutMs
   * @param {AbortSignal} [signal]
   */
  async #fetchJson(transport, method, pathName, body, timeoutMs, signal) {
    const url = `${transport.baseUrl}${pathName.startsWith('/') ? pathName : `/${pathName}`}`;
    const headers = {
      Authorization: `Bearer ${transport.token}`,
      Accept: 'application/json',
    };
    let payload;
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    const signals = [AbortSignal.timeout(Math.max(1_000, timeoutMs))];
    if (signal) signals.push(signal);

    let response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: payload,
        signal: AbortSignal.any(signals),
      });
    } catch (error) {
      if (isTimeoutError(error)) {
        throw new OpenFuyaoError(
          `openFuyao 请求超时（${timeoutMs}ms）：${method} ${pathName}`,
          { code: 'TIMEOUT', cause: error },
        );
      }
      if (isConnectionError(error)) {
        throw new OpenFuyaoError(
          `无法连接 openFuyao 后端：${transport.baseUrl}`,
          { code: 'CONNECTION_FAILED', cause: error },
        );
      }
      throw new OpenFuyaoError(
        `openFuyao 请求失败：${describeError(error)}`,
        { code: 'REQUEST_FAILED', cause: error },
      );
    }

    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }

    if (!response.ok) {
      const envelope = data && typeof data === 'object' ? data.error : undefined;
      const code = typeof envelope?.code === 'string'
        ? envelope.code
        : `HTTP_${response.status}`;
      const message = typeof envelope?.message === 'string'
        ? envelope.message
        : typeof data === 'string' && data.trim()
          ? data.trim()
          : `openFuyao 返回 HTTP ${response.status}`;
      throw new OpenFuyaoError(message, {
        code,
        status: response.status,
        details: envelope?.details,
      });
    }
    return data;
  }
}

/**
 * Resolve the sidecar data directory.
 *
 * `profileContext` exists only when DSH launched this profile, and it is the
 * only per-profile root the Host can see. The inherited `DSH_PROFILE_DIR` is a
 * shell-tool variable, so relying on it gives every profile one database.
 *
 * @param {any} ctx
 * @param {Record<string, any>} config
 * @returns {string}
 */
export function resolveDataDir(ctx, config) {
  const configured = String(config?.dataDir ?? '').trim();
  if (configured) return path.resolve(configured);
  const profileDir = String(ctx?.get?.('profileContext')?.dir ?? '').trim();
  const base = profileDir || path.join(os.homedir(), '.dsh');
  return path.join(base, 'plugin-data', 'openfuyao');
}

/**
 * @param {Record<string, any>} config
 * @returns {string}
 */
export function resolveExternalToken(config) {
  const direct = String(config.token ?? '').trim();
  if (direct) return direct;

  const fromEnv = String(process.env.AUTH_TOKEN ?? '').trim();
  if (fromEnv) return fromEnv;

  const tokenFile = String(config.tokenFile ?? DEFAULT_TOKEN_FILE).trim();
  if (tokenFile) {
    const value = readEnvFileValue(tokenFile, 'AUTH_TOKEN');
    if (value) return value;
  }
  throw new OpenFuyaoError(
    '缺少外部后端 AUTH_TOKEN：在插件配置里设置 token/tokenFile，或导出 AUTH_TOKEN',
    { code: 'AUTH_TOKEN_MISSING' },
  );
}

/**
 * Read one KEY=VALUE from a systemd EnvironmentFile-style file.
 * @param {string} file
 * @param {string} key
 * @returns {string}
 */
export function readEnvFileValue(file, key) {
  let content;
  try {
    content = fs.readFileSync(file, 'utf8');
  } catch {
    return '';
  }
  const pattern = new RegExp(
    `^\\s*(?:export\\s+)?${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*=\\s*(.*)\\s*$`,
  );
  for (const line of content.split(/\r?\n/)) {
    const match = pattern.exec(line);
    if (!match) continue;
    return match[1].trim().replace(/^(['"])(.*)\1$/, '$2');
  }
  return '';
}
