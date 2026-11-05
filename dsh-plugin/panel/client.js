/**
 * openFuyao right-sidebar panel.
 *
 * The module is a plain `window.__ModuleLoader__` factory, like the harness's
 * own client plugins, so the bundle needs no build step. It registers one tab
 * with dsh-better-sidebar; that plugin lands the tab in DSH's native right
 * Sidebar (and in its own + menu), so the panel is reachable without a second
 * application shell or an iframe.
 *
 * When no environment is ready, the same tab renders the Host preflight and a
 * user-confirmed deployment action; otherwise it stays a status/diagnostics
 * view.
 */

window.__ModuleLoader__.load({
  id: '@mlt_123/dsh-openfuyao-panel-test',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const EN = {
      title: 'openFuyao',
      description: 'Inspect or install openFuyao on this host.',
      environments: 'Environments',
      clusters: 'Business clusters',
      apps: 'Applications',
      issues: 'Issues',
      refresh: 'Refresh',
      refreshing: 'Refreshing',
      loading: 'Reading openFuyao state…',
      emptyEnvironments: 'No environment recorded for this agent.',
      emptyClusters: 'No business cluster discovered.',
      emptyApps: 'No application installed through openFuyao.',
      openConsole: 'Console',
      openApp: 'Open',
      nodes: 'Nodes',
      lastUpdated: 'Updated',
      source: 'Source',
      errorTitle: 'Cannot read openFuyao state',
      errorHint: 'Check the plugin transport (external backend or bundled sidecar) and retry.',
      retry: 'Retry',
      modeSidecar: 'bundled sidecar',
      modeExternal: 'external backend',
      warnings: 'Warnings',
      noIssues: 'No issues reported.',
      askDsh: 'Ask DSH',
      askedDsh: 'Added to composer',
      askAll: 'Ask DSH about all issues',
      askAllShort: 'Analyze all',
      askNoSession: 'Open a session first',
      askFailed: 'Could not write to the composer. Open a session and try again.',
      deployTitle: 'Install openFuyao',
      deployDescription: 'Preflight this host, then install BKE and the openFuyao console.',
      preflight: 'Host preflight',
      preflightEmpty: 'No preflight report yet. Run a check.',
      preflightLoading: 'Running host preflight…',
      recheck: 'Recheck',
      rechecking: 'Checking…',
      confirmDeploy: 'Confirm deploy',
      confirmTitle: 'Deploy openFuyao on this host?',
      confirmBody: 'This installs BKE and the openFuyao console on {host}. It can take several minutes.',
      confirmAck: 'I confirm this is the target host and want to start the deployment.',
      startDeploy: 'Start deployment',
      cancelDeploy: 'Cancel deployment',
      cancelling: 'Cancelling…',
      deploying: 'Deploying',
      waitingConsole: 'Waiting for console',
      deployReady: 'Ready',
      deployFailed: 'Deployment failed',
      deployCancelled: 'Cancelled',
      deployPending: 'Ready to deploy',
      preflightReady: 'Preflight passed',
      preflightWarn: 'Preflight passed with warnings',
      preflightFailed: 'Preflight failed',
      passed: 'passed',
      failed: 'failed',
      checkedAt: 'Checked',
      phasePreflight: 'Host preflight',
      phaseInstallBke: 'Installing BKE',
      phaseBkeInit: 'Initializing bootstrap node',
      phaseWaitConsole: 'Waiting for console',
      phaseDone: 'Deployment complete',
      phaseStep: 'Step {index}/{total}',
      elapsed: 'Elapsed',
      stageHint: 'This stage usually takes a few minutes. Expand the live log to follow progress.',
      stageHintPreflight: 'Checking this host before installation…',
      startingDeploy: 'Re-running preflight and starting deployment…',
      failedAtStage: 'Failed during “{phase}”',
      cancelledAtStage: 'Cancelled during “{phase}”',
      liveLogs: 'Live log',
      showLogs: 'Show',
      hideLogs: 'Hide',
      logWaiting: 'Waiting for log output…',
      logUnavailable: 'Log is unavailable right now.',
      logRetrying: 'Log refresh failed; retrying…',
      logTruncated: 'Showing the most recent part of the log.',
      cancelConfirmTitle: 'Cancel this deployment?',
      cancelConfirmBody: 'Completed install steps are not rolled back. The current task stops as soon as possible.',
      keepDeploying: 'Keep deploying',
      confirmCancel: 'Yes, cancel',
      retryDeploy: 'Redeploy',
      pollFailed: 'Status refresh failed; retrying…',
      readyTitle: 'openFuyao is ready',
      host: 'Host',
      actionFailed: 'Action failed',
      cancel: 'Cancel',
      unknown: 'unknown',
    };

    const ZH = {
      title: 'openFuyao 部署',
      description: '查看当前宿主机的 openFuyao 状态，或完成安装。',
      environments: '环境',
      clusters: '业务集群',
      apps: '应用',
      issues: '问题',
      refresh: '刷新',
      refreshing: '刷新中',
      loading: '正在读取 openFuyao 状态…',
      emptyEnvironments: '当前 Agent 还没有环境记录。',
      emptyClusters: '还没有发现业务集群。',
      emptyApps: '还没有通过 openFuyao 安装应用。',
      openConsole: '控制台',
      openApp: '打开',
      nodes: '节点',
      lastUpdated: '更新于',
      source: '来源',
      errorTitle: '无法读取 openFuyao 状态',
      errorHint: '检查插件传输配置（外部后端或内置 sidecar），然后重试。',
      retry: '重试',
      modeSidecar: '内置 sidecar',
      modeExternal: '外部后端',
      warnings: '警告',
      noIssues: '没有发现问题。',
      askDsh: '询问 DSH',
      askedDsh: '已填入输入框',
      askAll: '让 DSH 分析全部问题',
      askAllShort: '全部问题',
      askNoSession: '请先打开一个会话',
      askFailed: '无法写入输入框，请先打开一个会话后重试。',
      deployTitle: '安装 openFuyao',
      deployDescription: '先预检本机，再安装 BKE 与 openFuyao 控制台。',
      preflight: '环境预检',
      preflightEmpty: '还没有预检报告，请先执行预检。',
      preflightLoading: '正在执行宿主机预检…',
      recheck: '重新预检',
      rechecking: '预检中…',
      confirmDeploy: '确认部署',
      confirmTitle: '在当前宿主机部署 openFuyao？',
      confirmBody: '将在 {host} 上安装 BKE 和 openFuyao 控制台，过程可能需要几分钟。',
      confirmAck: '我确认这是目标宿主机，并开始部署。',
      startDeploy: '开始部署',
      cancelDeploy: '取消部署',
      cancelling: '取消中…',
      deploying: '部署中',
      waitingConsole: '等待控制台',
      deployReady: '已就绪',
      deployFailed: '部署失败',
      deployCancelled: '已取消',
      deployPending: '待部署',
      preflightReady: '预检通过',
      preflightWarn: '预检通过（有警告）',
      preflightFailed: '预检未通过',
      passed: '通过',
      failed: '失败',
      checkedAt: '预检时间',
      phasePreflight: '环境预检',
      phaseInstallBke: '安装 BKE',
      phaseBkeInit: '初始化引导节点',
      phaseWaitConsole: '等待控制台就绪',
      phaseDone: '部署完成',
      phaseStep: '第 {index}/{total} 步',
      elapsed: '已用时',
      stageHint: '该阶段通常需要数分钟，可展开实时日志查看输出。',
      stageHintPreflight: '正在检查宿主机…',
      startingDeploy: '正在重新预检并启动部署…',
      failedAtStage: '部署在「{phase}」阶段失败',
      cancelledAtStage: '已取消（停在「{phase}」）',
      liveLogs: '实时日志',
      showLogs: '展开',
      hideLogs: '收起',
      logWaiting: '等待日志输出…',
      logUnavailable: '日志暂不可用。',
      logRetrying: '日志刷新失败，正在重试…',
      logTruncated: '仅显示最近部分日志。',
      cancelConfirmTitle: '取消本次部署？',
      cancelConfirmBody: '已执行的安装步骤不会回滚；确认后会尽快停止当前任务。',
      keepDeploying: '继续部署',
      confirmCancel: '确认取消',
      retryDeploy: '重新部署',
      pollFailed: '状态刷新失败，正在重试…',
      readyTitle: 'openFuyao 已就绪',
      host: '宿主机',
      actionFailed: '操作失败',
      cancel: '取消',
      unknown: '未知',
    };

    function text(ctx, key) {
      const value = ctx.locale.bind('openfuyao')(key);
      return value === key ? (EN[key] ?? key) : value;
    }

    const CSS = `
      @keyframes ofu-spin { to { transform: rotate(360deg); } }
      @keyframes ofu-flow {
        from { transform: translateX(-120%); }
        to { transform: translateX(120%); }
      }
      @keyframes ofu-pulse {
        0%, 100% { opacity: 0.45; }
        50% { opacity: 1; }
      }
      .ofu-scroll { scrollbar-width: thin; }
      .ofu-scroll::-webkit-scrollbar { width: 8px; }
      .ofu-scroll::-webkit-scrollbar-thumb {
        background: var(--dsw-alias-border-l2);
        border-radius: 4px;
      }
      .ofu-log { scrollbar-width: thin; }
      .ofu-log::-webkit-scrollbar { width: 6px; }
      .ofu-log::-webkit-scrollbar-thumb {
        background: var(--dsw-alias-border-l2);
        border-radius: 3px;
      }
      .ofu-btn { transition: background-color 120ms ease, border-color 120ms ease; }
      .ofu-btn:hover:not(:disabled) {
        background: var(--dsw-alias-bg-layer-2);
        border-color: var(--dsw-alias-border-l2);
      }
      .ofu-btn:disabled { opacity: 0.55; cursor: default; }
    `;

    function apiUrl(path = 'openfuyao/api/overview') {
      const base = document.baseURI || `${window.location.origin}/`;
      return new URL(path, base.endsWith('/') ? base : `${base}/`).toString();
    }

    async function fetchJson(path, { signal, method = 'GET', body } = {}) {
      const response = await fetch(apiUrl(path), {
        method,
        signal,
        cache: 'no-store',
        headers: {
          accept: 'application/json',
          ...(body === undefined ? {} : { 'content-type': 'application/json' }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      if (!response.ok) {
        const error = new Error(payload?.error?.message || `HTTP ${response.status}`);
        error.code = payload?.error?.code || `HTTP_${response.status}`;
        error.status = response.status;
        error.details = payload?.error?.details ?? null;
        throw error;
      }
      if (!payload || typeof payload !== 'object') {
        throw new Error('openFuyao panel returned an empty response');
      }
      return payload;
    }

    function loadPanel(signal) {
      return fetchJson('openfuyao/api/overview', { signal });
    }

    // POST, not GET: the Host route runs the host preflight upstream. A Host
    // from before the method change only serves GET, and a page refresh without
    // a plugin reload is a documented upgrade path, so fall back once.
    async function loadPlan(signal) {
      try {
        return await postJson('openfuyao/api/plan', {}, signal);
      } catch (error) {
        if (!isRouteUnavailable(error)) throw error;
        return fetchJson('openfuyao/api/plan', { signal });
      }
    }

    function loadEnvironments(signal) {
      return fetchJson('openfuyao/api/environments', { signal });
    }

    function loadLogTail(environmentId, signal) {
      const query = new URLSearchParams({ environment_id: environmentId, tail: '1' });
      return fetchJson(`openfuyao/api/logs?${query}`, { signal });
    }

    function loadLogs(environmentId, cursor, signal) {
      const query = new URLSearchParams({
        environment_id: environmentId,
        cursor: String(cursor),
      });
      return fetchJson(`openfuyao/api/logs?${query}`, { signal });
    }

    function postJson(path, body, signal) {
      return fetchJson(path, { method: 'POST', body, signal });
    }

    /**
     * Whether a panel route is missing from the loaded Host plugin.
     *
     * Client bundles are composed when the page loads, while Host code only
     * changes on a plugin reload. A browser bundle newer than the Host asks for
     * a POST route the Host never registered; that request falls through to the
     * Web static fallback, which answers a non-GET/HEAD request with a plain
     * 405 instead of the panel's JSON envelope.
     */
    function isRouteUnavailable(error) {
      const status = Number(error?.status);
      return status === 404
        || status === 405
        || error?.code === 'HTTP_404'
        || error?.code === 'HTTP_405'
        || error?.code === 'METHOD_NOT_ALLOWED';
    }

    function formatTime(value) {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString();
    }

    function statusColor(value) {
      const status = String(value || '').toLowerCase();
      if (/(error|fail|unhealthy|crash|backoff)/.test(status)) {
        return 'var(--dsw-alias-state-error-primary)';
      }
      if (/(ready|deployed|done|success|running)/.test(status)) {
        return 'var(--dsw-alias-state-success-primary)';
      }
      if (/(pending|warn|progress|deploy|prepar|creat|bootstrap|waiting)/.test(status)) {
        return 'var(--dsw-alias-state-warn-primary)';
      }
      return 'var(--dsw-alias-state-idle-primary)';
    }

    function modeLabel(mode, t) {
      if (mode === 'sidecar') return t('modeSidecar');
      if (mode === 'external') return t('modeExternal');
      return mode || t('unknown');
    }

    const PHASE_ORDER = ['preflight', 'install_bke', 'bke_init', 'wait_console'];
    const PHASE_TITLE = {
      preflight: 'phasePreflight',
      install_bke: 'phaseInstallBke',
      bke_init: 'phaseBkeInit',
      wait_console: 'phaseWaitConsole',
      done: 'phaseDone',
    };

    function phaseTitle(phase, t) {
      return PHASE_TITLE[phase] ? t(PHASE_TITLE[phase]) : '';
    }

    function phaseStep(phase) {
      const index = PHASE_ORDER.indexOf(phase);
      if (index >= 0) return index + 1;
      if (phase === 'done') return PHASE_ORDER.length;
      return null;
    }

    function formatElapsed(milliseconds) {
      const total = Math.max(0, Math.floor(Number(milliseconds) / 1000) || 0);
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      const seconds = total % 60;
      const mm = String(minutes).padStart(2, '0');
      const ss = String(seconds).padStart(2, '0');
      return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
    }

    function stripAnsi(value) {
      return String(value ?? '').replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '');
    }

    function oneLineLog(value, limit = 320) {
      const text = stripAnsi(value).replace(/\s+/g, ' ').trim();
      return text.length > limit ? `${text.slice(0, limit)}…` : text;
    }

    function Logo({ size = 18 }) {
      return h('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        'aria-hidden': true, style: { flex: '0 0 auto' },
      },
      h('path', {
        d: 'M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9Z',
        stroke: 'currentColor', strokeWidth: 1.6, strokeLinejoin: 'round',
      }),
      h('path', {
        d: 'm4.4 7.6 7.6 4.3 7.6-4.3M12 11.9V21',
        stroke: 'currentColor', strokeWidth: 1.4, strokeLinejoin: 'round',
      }));
    }

    function RefreshIcon({ size = 14 }) {
      return h('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        'aria-hidden': true,
      },
      h('path', {
        d: 'M20 11a8 8 0 1 0-2.34 5.66M20 5v6h-6',
        stroke: 'currentColor', strokeWidth: 1.8,
        strokeLinecap: 'round', strokeLinejoin: 'round',
      }));
    }

    function ServerIcon({ size = 14 }) {
      return h('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        'aria-hidden': true, style: { flex: '0 0 auto' },
      },
      h('rect', {
        x: 3.5, y: 4, width: 17, height: 7, rx: 1.6,
        stroke: 'currentColor', strokeWidth: 1.6,
      }),
      h('rect', {
        x: 3.5, y: 13, width: 17, height: 7, rx: 1.6,
        stroke: 'currentColor', strokeWidth: 1.6,
      }),
      h('path', {
        d: 'M7 7.5h.01M7 16.5h.01',
        stroke: 'currentColor', strokeWidth: 2.2, strokeLinecap: 'round',
      }));
    }

    function ExternalIcon({ size = 11 }) {
      return h('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        'aria-hidden': true, style: { flex: '0 0 auto' },
      },
      h('path', {
        d: 'M14 4h6v6M20 4l-8 8M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5',
        stroke: 'currentColor', strokeWidth: 1.8,
        strokeLinecap: 'round', strokeLinejoin: 'round',
      }));
    }

    function StatusPill({ value, label, tone, pulse = false }) {
      const color = statusColor(tone ?? value);
      return h('span', {
        style: {
          display: 'inline-flex', alignItems: 'center', gap: 5,
          flex: '0 0 auto', fontSize: 11, fontWeight: 600, color,
        },
      },
      h('span', {
        style: {
          width: 6, height: 6, borderRadius: '50%',
          background: color, boxShadow: `0 0 0 2px color-mix(in srgb, ${color} 16%, transparent)`,
          animation: pulse ? 'ofu-pulse 1.4s ease-in-out infinite' : 'none',
        },
      }),
      label ?? value ?? '—');
    }

    function Spinner({ size = 12 }) {
      return h('span', {
        'aria-hidden': true,
        style: {
          display: 'inline-block', width: size, height: size, flex: '0 0 auto',
          borderRadius: '50%',
          border: '2px solid var(--dsw-alias-border-l2)',
          borderTopColor: 'var(--dsw-alias-brand-primary)',
          animation: 'ofu-spin 0.8s linear infinite',
        },
      });
    }

    function Progress({ value, active = false, failed = false }) {
      const pct = Math.max(0, Math.min(100, Number(value) || 0));
      const color = failed
        ? 'var(--dsw-alias-state-error-primary)'
        : 'var(--dsw-alias-brand-primary)';
      return h('div', {
        style: {
          display: 'flex', alignItems: 'center', gap: 8, marginTop: 8,
        },
      },
      h('div', {
        role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': pct,
        style: {
          flex: 1, height: 6, borderRadius: 3, overflow: 'hidden',
          background: 'var(--dsw-alias-bg-layer-2)',
        },
      },
      h('div', {
        style: {
          width: `${pct}%`, height: '100%', borderRadius: 3,
          background: color, position: 'relative', overflow: 'hidden',
          transition: 'width 400ms ease',
        },
      },
      active
        ? h('div', {
          style: {
            position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
            background: 'linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.55), transparent)',
            animation: 'ofu-flow 1.6s linear infinite',
          },
        })
        : null)),
      h('span', {
        style: {
          minWidth: 30, textAlign: 'right', fontSize: 10,
          color: 'var(--dsw-alias-label-secondary)',
          fontVariantNumeric: 'tabular-nums',
        },
      }, `${pct}%`));
    }

    function LinkButton({ href, label, compact = false }) {
      return h('a', {
        href, target: '_blank', rel: 'noreferrer',
        style: {
          display: 'inline-flex', alignItems: 'center', gap: 4,
          color: 'var(--dsw-alias-brand-primary)', textDecoration: 'none',
          fontSize: compact ? 11 : 12, fontWeight: 500,
        },
      }, h(ExternalIcon, { size: compact ? 10 : 11 }), label);
    }

    function Empty({ children }) {
      return h('div', {
        style: {
          padding: '12px 10px', borderRadius: 8,
          border: '1px dashed var(--dsw-alias-border-l1)',
          color: 'var(--dsw-alias-label-secondary)', fontSize: 12,
        },
      }, children);
    }

    function Section({ title, count, action, children }) {
      return h('section', { style: { marginTop: 16 } },
        h('div', {
          style: {
            display: 'flex', alignItems: 'center', gap: 8, marginBottom: 7,
          },
        },
        h('div', {
          style: {
            fontSize: 11, fontWeight: 700, letterSpacing: '0.05em',
            textTransform: 'uppercase', color: 'var(--dsw-alias-label-secondary)',
          },
        }, title),
        typeof count === 'number'
          ? h('span', {
            style: {
              fontSize: 10, lineHeight: '16px', minWidth: 18, padding: '0 5px',
              textAlign: 'center', borderRadius: 8,
              background: 'var(--dsw-alias-bg-layer-2)',
              color: 'var(--dsw-alias-label-secondary)',
            },
          }, count)
          : null,
        action ? h('div', { style: { marginLeft: 'auto' } }, action) : null),
        children);
    }

    function SummaryCard({ label, value, accent }) {
      return h('div', {
        style: {
          minWidth: 0, padding: '8px 9px', borderRadius: 9,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: 'var(--dsw-alias-bg-layer-1)',
        },
      },
      h('div', {
        style: {
          fontSize: 20, lineHeight: '24px', fontWeight: 650,
          color: accent || 'var(--dsw-alias-label-primary)',
        },
      }, value),
      h('div', {
        style: {
          marginTop: 2, fontSize: 10.5,
          color: 'var(--dsw-alias-label-secondary)',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        },
      }, label));
    }

    function ErrorState({ t, error, onRetry, disabled }) {
      return h('div', {
        style: {
          margin: 12, padding: 12, borderRadius: 9,
          border: '1px solid color-mix(in srgb, var(--dsw-alias-state-error-primary) 32%, var(--dsw-alias-border-l1))',
          background: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 8%, transparent)',
        },
      },
      h('div', {
        style: { fontSize: 13, fontWeight: 600, color: 'var(--dsw-alias-state-error-primary)' },
      }, t('errorTitle')),
      h('div', {
        style: { marginTop: 6, fontSize: 12, lineHeight: '18px', overflowWrap: 'anywhere' },
      }, error?.message || String(error)),
      error?.code
        ? h('code', {
          style: {
            display: 'inline-block', marginTop: 7, padding: '2px 5px',
            borderRadius: 4, fontSize: 10.5,
            background: 'var(--dsw-alias-bg-layer-2)',
            color: 'var(--dsw-alias-label-secondary)',
          },
        }, error.code)
        : null,
      h('div', {
        style: {
          marginTop: 8, fontSize: 11, lineHeight: '17px',
          color: 'var(--dsw-alias-label-secondary)',
        },
      }, t('errorHint')),
      h('button', {
        type: 'button', className: 'ofu-btn', onClick: onRetry, disabled,
        style: {
          marginTop: 10, padding: '5px 10px', borderRadius: 6,
          border: '1px solid var(--dsw-alias-border-l2)',
          background: 'var(--dsw-alias-bg-layer-1)',
          color: 'var(--dsw-alias-label-primary)', fontSize: 12, cursor: 'pointer',
        },
      }, t('retry')));
    }

    function Loading({ t }) {
      return h('div', {
        style: {
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: 10, minHeight: 220, padding: 24,
          color: 'var(--dsw-alias-label-secondary)', fontSize: 12,
        },
      },
      h('div', {
        style: {
          width: 22, height: 22, borderRadius: '50%',
          border: '2px solid var(--dsw-alias-border-l2)',
          borderTopColor: 'var(--dsw-alias-brand-primary)',
          animation: 'ofu-spin 0.8s linear infinite',
        },
      }),
      t('loading'));
    }

    function deployStatusLabel(status, t) {
      if (status === 'bootstrapping') return t('deploying');
      if (status === 'waiting_console') return t('waitingConsole');
      if (status === 'ready') return t('deployReady');
      if (status === 'failed') return t('deployFailed');
      if (status === 'cancelled') return t('deployCancelled');
      return t('deployPending');
    }

    function PreflightRow({ check }) {
      const status = String(check?.status || '').toLowerCase();
      const color = status === 'pass'
        ? 'var(--dsw-alias-state-success-primary)'
        : status === 'warn'
          ? 'var(--dsw-alias-state-warn-primary)'
          : 'var(--dsw-alias-state-error-primary)';
      return h('div', {
        style: {
          display: 'flex', gap: 7, padding: '6px 0',
          borderTop: '1px solid var(--dsw-alias-border-l1)',
        },
      },
      h('span', {
        style: {
          width: 14, flex: '0 0 auto', textAlign: 'center',
          color, fontWeight: 700, fontSize: 12,
        },
      }, status === 'pass' ? '✓' : status === 'warn' ? '!' : '×'),
      h('div', { style: { minWidth: 0, flex: 1 } },
        h('div', { style: { display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' } },
          h('span', { style: { fontSize: 11.5, fontWeight: 600 } },
            check?.title || check?.code || ''),
          h('span', {
            style: {
              fontSize: 10.5, lineHeight: '16px',
              color: 'var(--dsw-alias-label-secondary)',
              overflowWrap: 'anywhere',
            },
          }, check?.message || ''))));
    }

    function PreflightList({ report, t }) {
      if (!report) return h(Empty, null, t('preflightEmpty'));
      const checks = Array.isArray(report.checks) ? report.checks : [];
      const summary = report.summary || {};
      const pass = Number(summary.pass) || 0;
      const warn = Number(summary.warn) || 0;
      const fail = Number(summary.fail) || 0;
      const verdict = report.ready
        ? (warn > 0 ? t('preflightWarn') : t('preflightReady'))
        : t('preflightFailed');
      const verdictColor = !report.ready
        ? 'var(--dsw-alias-state-error-primary)'
        : warn > 0
          ? 'var(--dsw-alias-state-warn-primary)'
          : 'var(--dsw-alias-state-success-primary)';
      return h('div', { style: { marginTop: 4 } },
        h('div', {
          style: {
            display: 'flex', gap: 10, flexWrap: 'wrap',
            fontSize: 10.5, fontWeight: 600, alignItems: 'center',
          },
        },
        h('span', { style: { color: 'var(--dsw-alias-state-success-primary)' } }, `${pass} ${t('passed')}`),
        h('span', { style: { color: 'var(--dsw-alias-state-warn-primary)' } }, `${warn} ${t('warnings')}`),
        h('span', { style: { color: 'var(--dsw-alias-state-error-primary)' } }, `${fail} ${t('failed')}`),
        h('span', {
          style: { marginLeft: 'auto', color: verdictColor },
        }, verdict)),
        checks.length
          ? h('div', { style: { marginTop: 3 } },
            checks.map((check, index) => h(PreflightRow, {
              key: `${check.code || 'check'}-${index}`, check,
            })))
          : null);
    }

    function ConfirmDeploy({ host, retry = false, t, onCancel, onConfirm }) {
      const [ack, setAck] = React.useState(false);
      return h('div', {
        style: {
          marginTop: 10, padding: 10, borderRadius: 8,
          border: '1px solid color-mix(in srgb, var(--dsw-alias-state-warn-primary) 32%, var(--dsw-alias-border-l1))',
          background: 'color-mix(in srgb, var(--dsw-alias-state-warn-primary) 7%, transparent)',
        },
      },
      h('div', { style: { fontSize: 12, fontWeight: 600 } }, t('confirmTitle')),
      h('div', {
        style: {
          marginTop: 4, fontSize: 11, lineHeight: '16px',
          color: 'var(--dsw-alias-label-secondary)',
        },
      }, String(t('confirmBody')).replace('{host}', host || t('host'))),
      h('label', {
        style: {
          display: 'flex', alignItems: 'flex-start', gap: 6,
          marginTop: 8, fontSize: 11, lineHeight: '16px', cursor: 'pointer',
        },
      },
      h('input', {
        type: 'checkbox', checked: ack,
        onChange: (event) => setAck(event.target.checked),
        style: { marginTop: 2, accentColor: 'var(--dsw-alias-brand-primary)' },
      }),
      h('span', null, t('confirmAck'))),
      h('div', {
        style: { display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 8 },
      },
      h('button', {
        type: 'button', className: 'ofu-btn', onClick: onCancel,
        style: {
          padding: '4px 9px', borderRadius: 6,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
          fontSize: 11, cursor: 'pointer',
        },
      }, t('cancel')),
      h('button', {
        type: 'button', className: 'ofu-btn', onClick: onConfirm, disabled: !ack,
        style: {
          padding: '4px 9px', borderRadius: 6, border: 'none',
          background: 'var(--dsw-alias-brand-primary)', color: '#fff',
          fontSize: 11, fontWeight: 600,
          cursor: ack ? 'pointer' : 'default', opacity: ack ? 1 : 0.55,
        },
      }, t(retry ? 'retryDeploy' : 'startDeploy'))));
    }

    function useElapsed(startedAt, finishedAt, active) {
      const [now, setNow] = React.useState(() => Date.now());
      React.useEffect(() => {
        if (!active) return undefined;
        setNow(Date.now());
        const timer = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(timer);
      }, [active, startedAt, finishedAt]);
      if (!startedAt) return null;
      const start = new Date(startedAt).getTime();
      if (Number.isNaN(start)) return null;
      const end = finishedAt ? new Date(finishedAt).getTime() : now;
      return Math.max(0, (Number.isNaN(end) ? now : end) - start);
    }

    function PhaseLine({ environment, t }) {
      const status = environment?.status || 'pending';
      const active = status === 'bootstrapping' || status === 'waiting_console';
      const failed = status === 'failed';
      const cancelled = status === 'cancelled';
      const elapsedMs = useElapsed(environment?.started_at, environment?.finished_at, active);
      if (!active && !failed && !cancelled) return null;

      const phase = environment?.phase || '';
      const title = phaseTitle(phase, t)
        || (failed ? t('deployFailed') : cancelled ? t('deployCancelled') : t('deploying'));
      const index = phaseStep(phase);
      const step = index
        ? String(t('phaseStep'))
          .replace('{index}', String(index))
          .replace('{total}', String(PHASE_ORDER.length))
        : '';
      const elapsed = elapsedMs === null ? '' : `${t('elapsed')} ${formatElapsed(elapsedMs)}`;
      const summary = active
        ? [title, step, elapsed].filter(Boolean).join(' · ')
        : `${failed
          ? String(t('failedAtStage')).replace('{phase}', title)
          : String(t('cancelledAtStage')).replace('{phase}', title)}${elapsed ? ` · ${elapsed}` : ''}`;
      const color = failed
        ? 'var(--dsw-alias-state-error-primary)'
        : cancelled
          ? 'var(--dsw-alias-label-secondary)'
          : 'var(--dsw-alias-label-primary)';

      return h('div', { style: { marginTop: 8 } },
        h('div', {
          style: {
            display: 'flex', alignItems: 'center', gap: 7,
            fontSize: 11.5, fontWeight: 600, color, overflowWrap: 'anywhere',
          },
        },
        active ? h(Spinner, { size: 12 }) : null,
        h('span', null, summary)),
        active
          ? h('div', {
            style: {
              marginTop: 3, fontSize: 10.5, lineHeight: '15px',
              color: 'var(--dsw-alias-label-secondary)',
            },
          }, phase === 'preflight' ? t('stageHintPreflight') : t('stageHint'))
          : null);
    }

    function LiveLog({ environment, active, failed, visible, t }) {
      const environmentId = environment?.id || '';
      const startedAt = environment?.started_at || '';
      const [expanded, setExpanded] = React.useState(false);
      const [log, setLog] = React.useState({ lines: [], error: null, ready: false, truncated: false });
      const cursorRef = React.useRef(0);
      const scrollRef = React.useRef(null);

      React.useEffect(() => {
        if (failed) setExpanded(true);
      }, [failed]);

      React.useEffect(() => {
        if (!visible || !environmentId || (!active && !failed)) return undefined;
        const controller = new AbortController();
        let cancelled = false;
        let timer = null;
        let initialized = false;
        cursorRef.current = 0;
        setLog({ lines: [], error: null, ready: false, truncated: false });

        const merge = (page, reset) => {
          const incoming = Array.isArray(page?.lines) ? page.lines : [];
          if (reset) {
            setLog({
              lines: incoming.slice(-300),
              error: null,
              ready: true,
              truncated: Boolean(page?.truncated),
            });
            return;
          }
          if (incoming.length === 0) {
            setLog((previous) => ({ ...previous, error: null, ready: true }));
            return;
          }
          setLog((previous) => ({
            lines: [...previous.lines, ...incoming].slice(-300),
            error: null,
            ready: true,
            truncated: previous.truncated || Boolean(page?.truncated),
          }));
        };

        const poll = async () => {
          const reset = !initialized;
          const page = reset
            ? await loadLogTail(environmentId, controller.signal)
            : await loadLogs(environmentId, cursorRef.current, controller.signal);
          if (cancelled) return;
          initialized = true;
          const next = Number(page?.next_cursor);
          if (Number.isFinite(next) && next >= 0) cursorRef.current = next;
          merge(page, reset);
        };

        const fail = (error) => {
          if (cancelled || error?.name === 'AbortError') return;
          setLog((previous) => ({ ...previous, error }));
        };

        poll().catch(fail).finally(() => {
          if (cancelled) return;
          timer = setInterval(() => {
            poll().catch(fail);
          }, active ? 2000 : 15000);
        });

        return () => {
          cancelled = true;
          if (timer) clearInterval(timer);
          controller.abort();
        };
      }, [visible, environmentId, startedAt, active, failed]);

      React.useEffect(() => {
        const node = scrollRef.current;
        if (!expanded || !node) return;
        node.scrollTop = node.scrollHeight;
      }, [expanded, log.lines.length]);

      const lines = log.lines;
      let lastLine = '';
      for (let index = lines.length - 1; index >= 0; index -= 1) {
        const text = oneLineLog(lines[index]);
        if (text) {
          lastLine = text;
          break;
        }
      }
      const placeholder = log.error && lines.length === 0
        ? t('logUnavailable')
        : t('logWaiting');

      return h('div', { style: { marginTop: 9 } },
        h('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
          h('span', {
            style: {
              width: 6, height: 6, borderRadius: '50%', flex: '0 0 auto',
              background: failed
                ? 'var(--dsw-alias-state-error-primary)'
                : 'var(--dsw-alias-state-success-primary)',
              animation: active ? 'ofu-pulse 1.4s ease-in-out infinite' : 'none',
            },
          }),
          h('span', {
            style: {
              flex: '0 0 auto', fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
              textTransform: 'uppercase', color: 'var(--dsw-alias-label-secondary)',
            },
          }, t('liveLogs')),
          log.truncated
            ? h('span', {
              style: {
                flex: '0 1 auto', minWidth: 0, fontSize: 9,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                color: 'var(--dsw-alias-label-secondary)',
              },
            }, t('logTruncated'))
            : null,
          h('button', {
            type: 'button', className: 'ofu-btn',
            onClick: () => setExpanded((value) => !value),
            style: {
              flex: '0 0 auto', marginLeft: 'auto', padding: '1px 6px', borderRadius: 5,
              border: '1px solid var(--dsw-alias-border-l1)',
              background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
              fontSize: 10, cursor: 'pointer',
            },
          }, expanded ? t('hideLogs') : t('showLogs'))),
        expanded
          ? h('div', {
            ref: scrollRef,
            className: 'ofu-log',
            style: {
              marginTop: 4, padding: '6px 8px', maxHeight: 148, overflowY: 'auto',
              borderRadius: 7, border: '1px solid var(--dsw-alias-border-l1)',
              background: 'var(--dsw-alias-bg-layer-2)',
              fontFamily: 'var(--dsw-font-family-mono, ui-monospace, monospace)',
              fontSize: 10, lineHeight: '15px',
              whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
              color: 'var(--dsw-alias-label-secondary)',
            },
          },
          lines.length
            ? lines.map((line, index) => h('div', { key: index }, stripAnsi(line)))
            : h('div', null, placeholder),
          log.error && lines.length > 0
            ? h('div', {
              style: { marginTop: 3, color: 'var(--dsw-alias-state-warn-primary)' },
            }, t('logRetrying'))
            : null)
          : h('div', {
            style: {
              marginTop: 3,
              fontFamily: 'var(--dsw-font-family-mono, ui-monospace, monospace)',
              fontSize: 10, color: 'var(--dsw-alias-label-secondary)',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            },
          }, lastLine || placeholder));
    }

    function DeploymentCard({ environment, preflight, action, allowDeploy, planning, visible, pollError, t, onRecheck, onDeploy, onCancel }) {
      const [confirming, setConfirming] = React.useState(false);
      const [cancelConfirming, setCancelConfirming] = React.useState(false);
      const status = environment?.status || 'pending';
      const active = status === 'bootstrapping' || status === 'waiting_console';
      const ready = status === 'ready';
      const failed = status === 'failed';
      const cancelled = status === 'cancelled';
      const canDeploy = allowDeploy !== false && Boolean(preflight?.ready) && !active && !ready;
      const retry = failed || cancelled;
      const host = environment?.host || preflight?.host || '';
      const progress = Number(environment?.progress) || 0;
      const tone = ready ? 'ready' : failed ? 'failed' : active ? 'bootstrapping' : 'pending';
      const busy = ['rechecking', 'deploying', 'cancelling'].includes(action.phase);
      const failure = action.error
        ? {
          code: action.error.code,
          message: action.error.message || String(action.error),
        }
        : failed && environment?.error_message
          ? {
            code: environment.error_code,
            message: environment.error_message,
          }
          : null;

      React.useEffect(() => {
        if (!canDeploy) setConfirming(false);
      }, [canDeploy]);

      React.useEffect(() => {
        if (!active) setCancelConfirming(false);
      }, [active]);

      return h('div', {
        style: {
          marginTop: 12, padding: '10px 11px', borderRadius: 10,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: 'var(--dsw-alias-bg-layer-1)',
        },
      },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        h(ServerIcon, { size: 15 }),
        h('div', { style: { flex: 1, minWidth: 0 } },
          h('div', {
            style: {
              fontSize: 12.5, fontWeight: 650,
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            },
          }, host || t('host')),
          h('div', {
            style: {
              marginTop: 1, fontSize: 10.5,
              color: 'var(--dsw-alias-label-secondary)',
            },
          }, t('deployDescription'))),
        h(StatusPill, {
          value: status, label: deployStatusLabel(status, t), tone, pulse: active,
        })),

      h(PhaseLine, { environment, t }),

      (active || failed || progress > 0)
        ? h(Progress, { value: progress, active, failed })
        : null,

      action.phase === 'deploying'
        ? h('div', {
          style: {
            display: 'flex', alignItems: 'center', gap: 6, marginTop: 7,
            fontSize: 10.5, color: 'var(--dsw-alias-label-secondary)',
          },
        }, h(Spinner, { size: 10 }), t('startingDeploy'))
        : null,

      failure
        ? h('div', {
          style: {
            marginTop: 8, padding: '7px 9px', borderRadius: 7,
            border: '1px solid color-mix(in srgb, var(--dsw-alias-state-error-primary) 30%, var(--dsw-alias-border-l1))',
            background: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 7%, transparent)',
            fontSize: 11, lineHeight: '16px',
            color: 'var(--dsw-alias-state-error-primary)', overflowWrap: 'anywhere',
          },
        },
        h('div', { style: { fontWeight: 600 } }, failure.message),
        failure.code
          ? h('div', {
            style: {
              marginTop: 2, fontSize: 9.5, opacity: 0.8,
              fontFamily: 'var(--dsw-font-family-mono, ui-monospace, monospace)',
            },
          }, failure.code)
          : null)
        : null,

      (active || failed) && environment?.id
        ? h(LiveLog, {
          environment, active, failed, visible, t,
        })
        : null,

      pollError
        ? h('div', {
          style: {
            marginTop: 7, fontSize: 10.5,
            color: 'var(--dsw-alias-state-warn-primary)',
          },
        }, t('pollFailed'))
        : null,

      h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 } },
        h('button', {
          type: 'button', className: 'ofu-btn',
          onClick: onRecheck, disabled: busy || active,
          style: {
            padding: '4px 9px', borderRadius: 6,
            border: '1px solid var(--dsw-alias-border-l1)',
            background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
            fontSize: 11, cursor: busy || active ? 'default' : 'pointer',
          },
        }, action.phase === 'rechecking' ? t('rechecking') : t('recheck')),
        active
          ? (cancelConfirming
            ? null
            : h('button', {
              type: 'button', className: 'ofu-btn',
              onClick: () => setCancelConfirming(true), disabled: busy,
              style: {
                padding: '4px 9px', borderRadius: 6,
                border: '1px solid color-mix(in srgb, var(--dsw-alias-state-error-primary) 40%, var(--dsw-alias-border-l1))',
                background: 'transparent', color: 'var(--dsw-alias-state-error-primary)',
                fontSize: 11, cursor: busy ? 'default' : 'pointer',
              },
            }, t('cancelDeploy')))
          : canDeploy
            ? h('button', {
              type: 'button', className: 'ofu-btn',
              onClick: () => setConfirming(true), disabled: busy,
              style: {
                padding: '4px 9px', borderRadius: 6, border: 'none',
                background: 'var(--dsw-alias-brand-primary)', color: '#fff',
                fontSize: 11, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
              },
            }, t(retry ? 'retryDeploy' : 'confirmDeploy'))
            : null),

      active && cancelConfirming
        ? h('div', {
          style: {
            marginTop: 8, padding: '8px 9px', borderRadius: 8,
            border: '1px solid color-mix(in srgb, var(--dsw-alias-state-error-primary) 30%, var(--dsw-alias-border-l1))',
            background: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 6%, transparent)',
          },
        },
        h('div', { style: { fontSize: 11.5, fontWeight: 600 } }, t('cancelConfirmTitle')),
        h('div', {
          style: {
            marginTop: 3, fontSize: 10.5, lineHeight: '15px',
            color: 'var(--dsw-alias-label-secondary)',
          },
        }, t('cancelConfirmBody')),
        h('div', {
          style: { display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 7 },
        },
        h('button', {
          type: 'button', className: 'ofu-btn',
          onClick: () => setCancelConfirming(false),
          disabled: action.phase === 'cancelling',
          style: {
            padding: '4px 9px', borderRadius: 6,
            border: '1px solid var(--dsw-alias-border-l1)',
            background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
            fontSize: 11, cursor: action.phase === 'cancelling' ? 'default' : 'pointer',
          },
        }, t('keepDeploying')),
        h('button', {
          type: 'button', className: 'ofu-btn',
          onClick: onCancel, disabled: busy,
          style: {
            padding: '4px 9px', borderRadius: 6, border: 'none',
            background: 'var(--dsw-alias-state-error-primary)', color: '#fff',
            fontSize: 11, fontWeight: 600, opacity: busy ? 0.55 : 1,
            cursor: busy ? 'default' : 'pointer',
          },
        }, action.phase === 'cancelling' ? t('cancelling') : t('confirmCancel'))))
        : null,

      confirming && canDeploy
        ? h(ConfirmDeploy, {
          host,
          retry,
          t,
          onCancel: () => setConfirming(false),
          onConfirm: () => { setConfirming(false); onDeploy(); },
        })
        : null,

      h('div', { style: { marginTop: 10 } },
        h('div', {
          style: { display: 'flex', alignItems: 'center', gap: 8 },
        },
        h('div', {
          style: {
            fontSize: 11, fontWeight: 700, letterSpacing: '0.04em',
            textTransform: 'uppercase', color: 'var(--dsw-alias-label-secondary)',
          },
        }, t('preflight')),
        h('div', {
          style: {
            marginLeft: 'auto', fontSize: 10,
            color: 'var(--dsw-alias-label-secondary)',
          },
        }, preflight?.checked_at ? `${t('checkedAt')} ${formatTime(preflight.checked_at)}` : '')),
        planning && !preflight
          ? h('div', {
            style: {
              padding: '8px 0 2px', fontSize: 11,
              color: 'var(--dsw-alias-label-secondary)',
            },
          }, t('preflightLoading'))
          : h(PreflightList, { report: preflight, t })));
    }

    function EnvironmentCard({ env, t }) {
      return h('div', {
        style: {
          padding: '10px 11px', borderRadius: 10,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: 'var(--dsw-alias-bg-layer-1)',
          display: 'flex', flexDirection: 'column', gap: 7,
        },
      },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        h(ServerIcon, { size: 15 }),
        h('div', { style: { flex: 1, minWidth: 0 } },
          h('div', {
            style: {
              fontSize: 12.5, fontWeight: 600,
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            },
          }, env.host || env.id),
          h('div', {
            style: {
              marginTop: 1, fontSize: 10.5,
              color: 'var(--dsw-alias-label-secondary)',
            },
          }, [env.phase, formatTime(env.updated_at)].filter(Boolean).join(' · '))),
        h(StatusPill, { value: env.status })),
      typeof env.progress === 'number' ? h(Progress, { value: env.progress }) : null,
      env.error_message
        ? h('div', {
          style: {
            fontSize: 11, lineHeight: '16px',
            color: 'var(--dsw-alias-state-error-primary)',
            overflowWrap: 'anywhere',
          },
        }, env.error_message)
        : null,
      env.console_url
        ? h('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap' } },
          h(LinkButton, { href: env.console_url, label: t('openConsole') }))
        : null);
    }

    function ClusterCard({ cluster, t }) {
      const nodes = Array.isArray(cluster.nodes) ? cluster.nodes : [];
      const ready = nodes.filter((node) => String(node?.status || '').toLowerCase() === 'ready').length;
      const total = nodes.length || Number(cluster.expected_node_count) || 0;
      return h('div', {
        style: {
          padding: '10px 11px', borderRadius: 10,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: 'var(--dsw-alias-bg-layer-1)',
          display: 'flex', flexDirection: 'column', gap: 5,
        },
      },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        h('div', {
          style: {
            flex: 1, minWidth: 0, fontSize: 12.5, fontWeight: 600,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          },
        }, cluster.name || cluster.id),
        h(StatusPill, { value: cluster.status })),
      cluster.endpoint
        ? h('div', {
          style: {
            fontSize: 10.5, color: 'var(--dsw-alias-label-secondary)',
            fontFamily: 'var(--dsw-font-family-mono, ui-monospace, monospace)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          },
        }, cluster.endpoint)
        : null,
      h('div', {
        style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' },
      }, `${t('nodes')}: ${total > 0 ? `${ready}/${total}` : '—'}`),
      typeof cluster.progress === 'number' ? h(Progress, { value: cluster.progress }) : null);
    }

    function AppRow({ app, t }) {
      return h('div', {
        style: {
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 10px', borderRadius: 8,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: 'var(--dsw-alias-bg-layer-1)',
        },
      },
      h('div', { style: { flex: 1, minWidth: 0 } },
        h('div', {
          style: {
            fontSize: 12, fontWeight: 600,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          },
        }, app.release_name || app.id),
        h('div', {
          style: {
            marginTop: 1, fontSize: 10.5,
            color: 'var(--dsw-alias-label-secondary)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          },
        }, [app.namespace, app.chart_name].filter(Boolean).join(' · '))),
      h(StatusPill, { value: app.status }),
      app.verify_url
        ? h(LinkButton, { href: app.verify_url, label: t('openApp'), compact: true })
        : null);
    }

    function sessionIdOf(props) {
      const direct = props?.scope?.sessionId ?? props?.sessionId;
      return typeof direct === 'string' ? direct : '';
    }

    /**
     * Append a prompt to the current session's composer draft. DSH exposes the
     * per-session input facade through `ctx.conversation`; `ctx.sessions.scope`
     * turns the session id into the scoped context that facade expects. This is
     * the same path dsh-better-sidebar uses for its "insert reference" action,
     * so the panel does not have to emulate typing into the Lexical editor.
     */
    function insertPrompt(ctx, sessionId, prompt) {
      try {
        if (!ctx || !sessionId || typeof ctx.get !== 'function') return false;
        const sessions = ctx.get('sessions');
        const conversation = ctx.get('conversation');
        if (!sessions || !conversation?.input || typeof sessions.scope !== 'function') return false;
        const actx = sessions.scope(sessionId);
        if (!actx) return false;
        const input = conversation.input.for(actx);
        if (!input || typeof input.setDraft !== 'function') return false;
        const current = String(input.state?.getSnapshot?.().draft ?? '');
        const next = current.trim()
          ? `${current.replace(/\s+$/, '')}\n\n${prompt}`
          : prompt;
        input.setDraft(next);
        if (typeof input.focus === 'function') input.focus();
        return true;
      } catch (error) {
        console.warn('[openfuyao] composer insert failed:', error);
        return false;
      }
    }

    function oneLine(value) {
      return String(value ?? '').replace(/\s+/g, ' ').trim();
    }

    function stateSummary(data) {
      const environments = Array.isArray(data?.environments) ? data.environments : [];
      const clusters = Array.isArray(data?.clusters) ? data.clusters : [];
      const apps = Array.isArray(data?.apps) ? data.apps : [];
      const issues = Array.isArray(data?.issues) ? data.issues : [];
      const errors = Array.isArray(data?.errors) ? data.errors : [];
      const envText = environments.length
        ? environments.map((env) => {
          const bits = [env.host || env.id, env.status, env.phase];
          if (typeof env.progress === 'number') bits.push(`${env.progress}%`);
          if (env.error_message) bits.push(`error=${oneLine(env.error_message)}`);
          return bits.filter(Boolean).join(' ');
        }).join('; ')
        : 'none';
      const clusterText = clusters.length
        ? clusters.map((cluster) => {
          const nodes = Array.isArray(cluster.nodes) ? cluster.nodes : [];
          const ready = nodes.filter((node) => String(node?.status || '').toLowerCase() === 'ready').length;
          const total = nodes.length || Number(cluster.expected_node_count) || 0;
          const bits = [cluster.name || cluster.id, cluster.status, cluster.endpoint];
          if (total > 0) bits.push(`nodes=${ready}/${total}`);
          return bits.filter(Boolean).join(' ');
        }).join('; ')
        : 'none';
      const appText = apps.length
        ? apps.map((app) => [app.release_name || app.id, app.namespace, app.status, app.verify_url]
          .filter(Boolean).join(' ')).join('; ')
        : 'none';
      const issueText = issues.length
        ? issues.slice(0, 10).map((issue) => `${issue.title || issue.code} (${issue.code}/${issue.severity})`).join('; ')
        : 'none';
      const errorText = errors.length
        ? errors.slice(0, 5).map((message) => oneLine(message)).join('; ')
        : 'none';
      return {
        envText, clusterText, appText, issueText, errorText,
        issueCount: issues.length,
        errorCount: errors.length,
      };
    }

    function promptHeader(data, locale) {
      const zh = String(locale || '').toLowerCase().startsWith('zh');
      const summary = stateSummary(data);
      return {
        zh,
        refreshedAt: data?.refreshedAt || '',
        mode: data?.transport?.mode || '',
        ...summary,
      };
    }

    function buildIssuePrompt(issue, data, locale) {
      const info = promptHeader(data, locale);
      const resource = issue.resource_name || issue.resource_id || (info.zh ? '未指定' : 'unspecified');
      if (info.zh) {
        return [
          '请帮我诊断下面这个 openFuyao 问题，并在执行任何变更前先向我确认。',
          '',
          `问题：${oneLine(issue.title) || issue.code || '未知问题'}`,
          `代码：${issue.code || '—'} · 级别：${issue.severity || '—'} · 来源：${issue.source || '—'}`,
          `资源：${resource}`,
          `说明：${oneLine(issue.message) || '无'}`,
          `已有建议：${oneLine(issue.remediation) || '无'}`,
          '',
          `当前状态（采集于 ${info.refreshedAt || '刚刚'}，传输：${info.mode || '未知'}）：`,
          `- 环境：${info.envText}`,
          `- 业务集群：${info.clusterText}`,
          `- 应用：${info.appText}`,
          `- 全部问题：${info.issueText}`,
          `- 观察错误：${info.errorText}`,
          '',
          '请先调用 openfuyao_status / openfuyao_environments / openfuyao_logs 复核事实，然后给出：',
          '1. 现象与根因判断；',
          '2. 影响面；',
          '3. 排查/修复步骤；',
          '4. 如需变更，说明准备调用哪个 openfuyao_* 工具、参数是什么，并等我确认后再执行。',
        ].join('\n');
      }
      return [
        'Help me diagnose the following openFuyao issue. Ask for confirmation before any change.',
        '',
        `Issue: ${oneLine(issue.title) || issue.code || 'unknown issue'}`,
        `Code: ${issue.code || '—'} · Severity: ${issue.severity || '—'} · Source: ${issue.source || '—'}`,
        `Resource: ${resource}`,
        `Details: ${oneLine(issue.message) || 'none'}`,
        `Existing recommendation: ${oneLine(issue.remediation) || 'none'}`,
        '',
        `Current state (observed ${info.refreshedAt || 'just now'}, transport: ${info.mode || 'unknown'}):`,
        `- Environment: ${info.envText}`,
        `- Business clusters: ${info.clusterText}`,
        `- Applications: ${info.appText}`,
        `- All issues: ${info.issueText}`,
        `- Observation errors: ${info.errorText}`,
        '',
        'First verify the facts through openfuyao_status / openfuyao_environments / openfuyao_logs, then provide:',
        '1. symptoms and likely root cause;',
        '2. blast radius;',
        '3. investigation/remediation steps;',
        '4. if a change is needed, name the openfuyao_* tool and arguments and wait for my confirmation before executing.',
      ].join('\n');
    }

    function buildAllIssuesPrompt(data, locale) {
      const info = promptHeader(data, locale);
      const issues = Array.isArray(data?.issues) ? data.issues : [];
      if (info.zh) {
        return [
          '请帮我分析当前 openFuyao 的全部问题，并在执行任何变更前先向我确认。',
          '',
          `采集时间：${info.refreshedAt || '刚刚'}；传输：${info.mode || '未知'}；问题数：${info.issueCount}`,
          `环境：${info.envText}`,
          `业务集群：${info.clusterText}`,
          `应用：${info.appText}`,
          `观察错误：${info.errorText}`,
          '',
          '问题列表：',
          ...(issues.length
            ? issues.map((issue, index) => `${index + 1}. ${oneLine(issue.title) || issue.code}（${issue.code}/${issue.severity}，${issue.source}）${issue.message ? `：${oneLine(issue.message)}` : ''}`)
            : ['（无）']),
          '',
          '请先调用 openfuyao_status / openfuyao_environments / openfuyao_logs 复核事实，然后按严重程度排序，给出：',
          '1. 每个问题的根因判断与影响面；',
          '2. 建议的处理顺序；',
          '3. 需要变更时准备调用哪个 openfuyao_* 工具、参数是什么，并等我确认后再执行。',
        ].join('\n');
      }
      return [
        'Help me analyze all current openFuyao issues. Ask for confirmation before any change.',
        '',
        `Observed: ${info.refreshedAt || 'just now'}; transport: ${info.mode || 'unknown'}; issues: ${info.issueCount}`,
        `Environment: ${info.envText}`,
        `Business clusters: ${info.clusterText}`,
        `Applications: ${info.appText}`,
        `Observation errors: ${info.errorText}`,
        '',
        'Issues:',
        ...(issues.length
          ? issues.map((issue, index) => `${index + 1}. ${oneLine(issue.title) || issue.code} (${issue.code}/${issue.severity}, ${issue.source})${issue.message ? `: ${oneLine(issue.message)}` : ''}`)
          : ['(none)']),
        '',
        'First verify the facts through openfuyao_status / openfuyao_environments / openfuyao_logs, then order the issues by severity and provide:',
        '1. root cause and blast radius for each issue;',
        '2. the recommended remediation order;',
        '3. if a change is needed, name the openfuyao_* tool and arguments and wait for my confirmation before executing.',
      ].join('\n');
    }

    function buildErrorMessagePrompt(message, data, locale) {
      return buildIssuePrompt({
        code: 'OVERVIEW_ERROR',
        severity: 'warn',
        source: 'overview',
        title: oneLine(message) || 'openFuyao observation error',
        message: String(message ?? ''),
        remediation: '',
      }, data, locale);
    }

    function AskButton({ label, title, disabled, asked, onClick }) {
      return h('button', {
        type: 'button', className: 'ofu-btn', onClick, disabled,
        title: disabled ? title : label,
        'aria-label': title || label,
        style: {
          display: 'inline-flex', alignItems: 'center', gap: 4,
          padding: '3px 7px', borderRadius: 6,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: asked ? 'color-mix(in srgb, var(--dsw-alias-brand-primary) 10%, transparent)' : 'transparent',
          color: asked ? 'var(--dsw-alias-brand-primary)' : 'var(--dsw-alias-label-secondary)',
          fontSize: 10.5, fontWeight: 500,
          cursor: disabled ? 'default' : 'pointer',
          opacity: disabled ? 0.5 : 1,
          flex: '0 0 auto',
        },
      }, asked ? '✓ ' : '', label);
    }

    function IssueRow({ issue, t, canAsk, asked, onAsk }) {
      const color = statusColor(issue.severity);
      return h('div', {
        style: {
          padding: '8px 10px', borderRadius: 8,
          border: `1px solid color-mix(in srgb, ${color} 28%, var(--dsw-alias-border-l1))`,
          background: `color-mix(in srgb, ${color} 6%, transparent)`,
        },
      },
      h('div', {
        style: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 11.5, fontWeight: 600 },
      },
      h('span', {
        style: { width: 6, height: 6, borderRadius: '50%', background: color, flex: '0 0 auto' },
      }),
      h('span', { style: { flex: 1, minWidth: 0 } }, issue.title || issue.code || issue.id)),
      issue.message
        ? h('div', {
          style: {
            marginTop: 4, fontSize: 11, lineHeight: '16px',
            color: 'var(--dsw-alias-label-secondary)', overflowWrap: 'anywhere',
          },
        }, issue.message)
        : null,
      issue.remediation
        ? h('div', {
          style: {
            marginTop: 4, fontSize: 10.5, lineHeight: '15px',
            color: 'var(--dsw-alias-label-secondary)', opacity: 0.9,
          },
        }, issue.remediation)
        : null,
      h('div', { style: { display: 'flex', justifyContent: 'flex-end', marginTop: 6 } },
        h(AskButton, {
          label: asked ? t('askedDsh') : t('askDsh'),
          title: canAsk ? t('askDsh') : t('askNoSession'),
          disabled: !canAsk,
          asked,
          onClick: onAsk,
        })));
    }

    function ErrorRow({ message, t, canAsk, asked, onAsk }) {
      return h('div', {
        style: {
          padding: '7px 9px', borderRadius: 7,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: 'var(--dsw-alias-bg-layer-1)',
          fontSize: 11, lineHeight: '16px',
          color: 'var(--dsw-alias-label-secondary)', overflowWrap: 'anywhere',
        },
      },
      h('div', null, message),
      h('div', { style: { display: 'flex', justifyContent: 'flex-end', marginTop: 5 } },
        h(AskButton, {
          label: asked ? t('askedDsh') : t('askDsh'),
          title: canAsk ? t('askDsh') : t('askNoSession'),
          disabled: !canAsk,
          asked,
          onClick: onAsk,
        })));
    }

    function Panel(props) {
      const t = (key) => text(props.ctx, key);
      const [state, setState] = React.useState({ phase: 'loading', data: null, error: null });
      const [requestId, setRequestId] = React.useState(0);
      const [planState, setPlanState] = React.useState({ phase: 'idle', data: null, error: null });
      const [planRequestId, setPlanRequestId] = React.useState(0);
      const [action, setAction] = React.useState({ phase: 'idle', error: null });
      const [lastPolledAt, setLastPolledAt] = React.useState(null);
      const [pollError, setPollError] = React.useState(false);
      const [asked, setAsked] = React.useState({});
      const [askError, setAskError] = React.useState(null);
      const visible = props.visible !== false;
      const requestRef = React.useRef(0);
      const planRequestRef = React.useRef(0);
      const pollFailures = React.useRef(0);
      // The two environment pollers below are mutually exclusive by status.
      // One latch keeps a slow backend (30 s timeout) from stacking ticks.
      const pollInFlight = React.useRef(false);
      const sessionId = sessionIdOf(props);

      React.useEffect(() => {
        if (!visible) return undefined;
        const controller = new AbortController();
        requestRef.current += 1;
        const current = requestRef.current;
        setState((previous) => ({
          phase: previous.data ? 'refreshing' : 'loading',
          data: previous.data,
          error: null,
        }));
        loadPanel(controller.signal).then((data) => {
          if (controller.signal.aborted || requestRef.current !== current) return;
          pollFailures.current = 0;
          setPollError(false);
          setLastPolledAt(data?.refreshedAt || new Date().toISOString());
          setState({ phase: 'ready', data, error: null });
        }).catch((error) => {
          if (controller.signal.aborted || error?.name === 'AbortError') return;
          if (requestRef.current !== current) return;
          setState((previous) => ({ phase: 'error', data: previous.data, error }));
        });
        return () => controller.abort();
      }, [requestId, visible]);

      const environmentStatus = state.data?.environments?.[0]?.status;
      const environmentId = state.data?.environments?.[0]?.id;

      React.useEffect(() => {
        if (!visible || !state.data) return undefined;
        if (environmentStatus === 'ready'
          || environmentStatus === 'bootstrapping'
          || environmentStatus === 'waiting_console') {
          return undefined;
        }
        const controller = new AbortController();
        planRequestRef.current += 1;
        const current = planRequestRef.current;
        setPlanState((previous) => ({
          phase: previous.data ? 'refreshing' : 'loading',
          data: previous.data,
          error: null,
        }));
        loadPlan(controller.signal).then((payload) => {
          if (controller.signal.aborted || planRequestRef.current !== current) return;
          setPlanState({ phase: 'ready', data: payload, error: null });
        }).catch((error) => {
          if (controller.signal.aborted || error?.name === 'AbortError') return;
          if (planRequestRef.current !== current) return;
          setPlanState((previous) => ({ phase: 'error', data: previous.data, error }));
        });
        return () => controller.abort();
      }, [visible, state.data?.refreshedAt, environmentStatus, planRequestId]);

      React.useEffect(() => {
        if (!visible) return undefined;
        if (environmentStatus !== 'bootstrapping' && environmentStatus !== 'waiting_console') {
          return undefined;
        }
        const controller = new AbortController();
        const timer = setInterval(() => {
          if (pollInFlight.current) return;
          pollInFlight.current = true;
          loadEnvironments(controller.signal).then((payload) => {
            const environments = Array.isArray(payload.environments) ? payload.environments : [];
            pollFailures.current = 0;
            setPollError(false);
            setLastPolledAt(payload.refreshedAt || new Date().toISOString());
            setState((previous) => (previous.data
              ? { ...previous, data: { ...previous.data, environments } }
              : previous));
            setPlanState((previous) => (previous.data
              ? { ...previous, data: { ...previous.data, environment: environments[0] || previous.data.environment } }
              : previous));
            const nextStatus = environments[0]?.status;
            if (nextStatus !== 'bootstrapping' && nextStatus !== 'waiting_console') {
              setRequestId((value) => value + 1);
            }
          }).catch(() => {
            pollFailures.current += 1;
            if (pollFailures.current >= 3) setPollError(true);
          }).finally(() => {
            pollInFlight.current = false;
          });
        }, 2000);
        return () => {
          clearInterval(timer);
          controller.abort();
        };
      }, [visible, environmentStatus, environmentId]);

      const hasData = Boolean(state.data);

      React.useEffect(() => {
        if (!visible || !hasData) return undefined;
        if (environmentStatus === 'ready'
          || environmentStatus === 'bootstrapping'
          || environmentStatus === 'waiting_console') {
          return undefined;
        }
        const controller = new AbortController();
        const timer = setInterval(() => {
          if (pollInFlight.current) return;
          pollInFlight.current = true;
          loadEnvironments(controller.signal).then((payload) => {
            const environments = Array.isArray(payload.environments) ? payload.environments : [];
            pollFailures.current = 0;
            setPollError(false);
            setLastPolledAt(payload.refreshedAt || new Date().toISOString());
            setState((previous) => (previous.data
              ? { ...previous, data: { ...previous.data, environments } }
              : previous));
          }).catch(() => {
            pollFailures.current += 1;
            if (pollFailures.current >= 3) setPollError(true);
          }).finally(() => {
            pollInFlight.current = false;
          });
        }, 5000);
        return () => {
          clearInterval(timer);
          controller.abort();
        };
      }, [visible, hasData, environmentStatus, environmentId]);

      const loading = state.phase === 'loading' || state.phase === 'refreshing';
      const data = state.data;
      const refresh = () => setRequestId((value) => value + 1);
      const locale = props.ctx?.locale?.getSnapshot?.().active ?? '';
      const ask = (key, prompt) => {
        const ok = insertPrompt(props.ctx, sessionId, prompt);
        if (ok) {
          setAsked((previous) => ({ ...previous, [key]: true }));
          setAskError(null);
        } else {
          setAskError(t('askFailed'));
        }
      };

      const environment = Array.isArray(data?.environments)
        ? data.environments[0]
        : (planState.data?.environment || null);
      const preflight = planState.data?.preflight || environment?.preflight || null;
      const plan = Array.isArray(planState.data?.plan) ? planState.data.plan : [];
      const ready = environment?.status === 'ready';
      const needsSetup = !ready;

      const replaceEnvironment = (next) => {
        if (!next) return;
        setState((previous) => (previous.data
          ? {
            ...previous,
            data: {
              ...previous.data,
              environments: [
                next,
                ...previous.data.environments.filter((item) => item.id !== next.id),
              ],
            },
          }
          : previous));
      };

      const recheck = async () => {
        setAction({ phase: 'rechecking', error: null });
        try {
          if (environment?.id
            && environment.status !== 'ready'
            && environment.status !== 'bootstrapping'
            && environment.status !== 'waiting_console') {
            let payload;
            try {
              payload = await postJson('openfuyao/api/preflight', {
                environment_id: environment.id,
              });
            } catch (error) {
              if (!isRouteUnavailable(error)) throw error;
              if (typeof console !== 'undefined' && typeof console.warn === 'function') {
                console.warn(
                  'openFuyao: recheck POST route is unavailable; falling back to the plan route',
                  error,
                );
              }
              // Older Host bundles only expose the read-only plan route (the
              // one that already rendered the checklist). Rechecking must still
              // refresh the report instead of pinning "HTTP 405" under the
              // button, so run the same dry-run plan through the GET route.
              payload = await loadPlan();
            }
            setPlanState((previous) => ({
              phase: 'ready',
              data: {
                ...(previous.data || {}),
                ...payload,
                environment: payload.environment || environment,
                preflight: payload.preflight || payload.environment?.preflight || null,
                // A recheck reports no plan (the stored plan is unchanged), so
                // keep the previous steps instead of blanking the list.
                plan: Array.isArray(payload.plan) && payload.plan.length > 0
                  ? payload.plan
                  : (previous.data?.plan || []),
              },
              error: null,
            }));
            replaceEnvironment(payload.environment);
          } else {
            const payload = await loadPlan();
            setPlanState({ phase: 'ready', data: payload, error: null });
            replaceEnvironment(payload.environment);
          }
          setAction({ phase: 'idle', error: null });
          setRequestId((value) => value + 1);
        } catch (error) {
          setAction({ phase: 'error', error });
        }
      };

      const deploy = async () => {
        const host = environment?.host || preflight?.host || '';
        setAction({ phase: 'deploying', error: null });
        try {
          const result = await postJson('openfuyao/api/deploy', { confirm: true, host });
          const next = result.environment || environment;
          setPlanState((previous) => ({
            phase: 'ready',
            data: {
              ...(previous.data || {}),
              environment: next,
              preflight: result.preflight || previous.data?.preflight || preflight,
              plan: Array.isArray(result.plan) ? result.plan : (previous.data?.plan || plan),
            },
            error: null,
          }));
          replaceEnvironment(next);
          setAction({ phase: 'idle', error: null });
          setRequestId((value) => value + 1);
        } catch (error) {
          if (error.details?.preflight) {
            setPlanState((previous) => ({
              phase: 'ready',
              data: {
                ...(previous.data || {}),
                environment: error.details.environment || previous.data?.environment || environment,
                preflight: error.details.preflight,
                plan: Array.isArray(error.details.plan) ? error.details.plan : (previous.data?.plan || plan),
              },
              error: null,
            }));
          }
          setAction({ phase: 'error', error });
        }
      };

      const cancelDeploy = async () => {
        if (!environment?.id) return;
        setAction({ phase: 'cancelling', error: null });
        try {
          const result = await postJson('openfuyao/api/cancel', {
            target: 'environment',
            id: environment.id,
          });
          setPlanState((previous) => ({
            phase: 'ready',
            data: {
              ...(previous.data || {}),
              environment: result.environment || environment,
            },
            error: null,
          }));
          replaceEnvironment(result.environment);
          setAction({ phase: 'idle', error: null });
          setRequestId((value) => value + 1);
        } catch (error) {
          setAction({ phase: 'error', error });
        }
      };

      const body = (() => {
        if (!data && state.phase === 'loading') return h(Loading, { t });
        if (!data && state.error) {
          return h(ErrorState, {
            t, error: state.error, onRetry: refresh, disabled: loading,
          });
        }
        if (!data) return h(Loading, { t });

        const environments = Array.isArray(data.environments) ? data.environments : [];
        const clusters = Array.isArray(data.clusters) ? data.clusters : [];
        const apps = Array.isArray(data.apps) ? data.apps : [];
        const issues = Array.isArray(data.issues) ? data.issues : [];
        const errors = Array.isArray(data.errors) ? data.errors : [];
        // Before openFuyao is installed the only actionable surface is the
        // preflight/deploy card. Overview issues there are observation noise
        // (missing kubeconfig, unreachable console), so the Issues section
        // stays hidden until installation has produced real state.
        const installed = ready || clusters.length > 0 || apps.length > 0;

        return h('div', { style: { padding: '0 12px 18px' } },
          ready
            ? h('div', {
              style: {
                marginTop: 12, padding: '9px 11px', borderRadius: 10,
                border: '1px solid color-mix(in srgb, var(--dsw-alias-state-success-primary) 30%, var(--dsw-alias-border-l1))',
                background: 'color-mix(in srgb, var(--dsw-alias-state-success-primary) 7%, transparent)',
                display: 'flex', alignItems: 'center', gap: 8,
              },
            },
            h('span', {
              style: {
                width: 7, height: 7, borderRadius: '50%', flex: '0 0 auto',
                background: 'var(--dsw-alias-state-success-primary)',
              },
            }),
            h('div', {
              style: {
                flex: 1, minWidth: 0, fontSize: 12, fontWeight: 600,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              },
            }, t('readyTitle')),
            data.console?.url
              ? h(LinkButton, { href: data.console.url, label: t('openConsole'), compact: true })
              : null)
            : null,
          needsSetup
            ? h(DeploymentCard, {
              environment,
              preflight,
              action,
              allowDeploy: data.panelDeploy !== false,
              planning: planState.phase === 'loading' || planState.phase === 'refreshing',
              visible,
              pollError,
              t,
              onRecheck: recheck,
              onDeploy: deploy,
              onCancel: cancelDeploy,
            })
            : h('div', {
              style: {
                display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                gap: 8, marginTop: 12,
              },
            },
            h(SummaryCard, { label: t('environments'), value: environments.length }),
            h(SummaryCard, { label: t('clusters'), value: clusters.length }),
            h(SummaryCard, { label: t('apps'), value: apps.length })),

          state.error
            ? h('div', {
              style: {
                marginTop: 12, padding: '8px 10px', borderRadius: 8,
                border: '1px solid color-mix(in srgb, var(--dsw-alias-state-error-primary) 30%, var(--dsw-alias-border-l1))',
                background: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 7%, transparent)',
                fontSize: 11, lineHeight: '16px', color: 'var(--dsw-alias-state-error-primary)',
              },
            }, state.error.message || String(state.error))
            : null,

          ready
            ? h(Section, { title: t('environments'), count: environments.length },
              h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
                environments.map((env) => h(EnvironmentCard, { key: env.id, env, t }))))
            : null,

          (ready || clusters.length > 0)
            ? h(Section, { title: t('clusters'), count: clusters.length },
              clusters.length
                ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
                  clusters.map((cluster) => h(ClusterCard, { key: cluster.id, cluster, t })))
                : h(Empty, null, t('emptyClusters')))
            : null,

          (ready || apps.length > 0)
            ? h(Section, { title: t('apps'), count: apps.length },
              apps.length
                ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
                  apps.map((app) => h(AppRow, { key: app.id, app, t })))
                : h(Empty, null, t('emptyApps')))
            : null,

          (installed && (issues.length > 0 || errors.length > 0))
            ? h(Section, {
              title: t('issues'),
              count: issues.length + errors.length,
              action: issues.length > 0
                ? h(AskButton, {
                  label: Boolean(asked.__all__) ? t('askedDsh') : t('askAllShort'),
                  title: sessionId ? t('askAll') : t('askNoSession'),
                  disabled: !sessionId,
                  asked: Boolean(asked.__all__),
                  onClick: () => ask('__all__', buildAllIssuesPrompt(data, locale)),
                })
                : null,
            },
            h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
              askError
                ? h('div', {
                  style: {
                    padding: '7px 9px', borderRadius: 7,
                    border: '1px solid color-mix(in srgb, var(--dsw-alias-state-error-primary) 30%, var(--dsw-alias-border-l1))',
                    background: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 7%, transparent)',
                    fontSize: 11, lineHeight: '16px',
                    color: 'var(--dsw-alias-state-error-primary)', overflowWrap: 'anywhere',
                  },
                }, askError)
                : null,
              issues.map((issue, index) => {
                const key = issue.id || `${issue.code || 'issue'}-${index}`;
                return h(IssueRow, {
                  key,
                  issue,
                  t,
                  canAsk: Boolean(sessionId),
                  asked: Boolean(asked[key]),
                  onAsk: () => ask(key, buildIssuePrompt(issue, data, locale)),
                });
              }),
              errors.map((message, index) => {
                const key = `error-${index}`;
                return h(ErrorRow, {
                  key,
                  message,
                  t,
                  canAsk: Boolean(sessionId),
                  asked: Boolean(asked[key]),
                  onAsk: () => ask(key, buildErrorMessagePrompt(message, data, locale)),
                });
              })))
            : null);
      })();

      return h('div', {
        className: 'ofu-scroll',
        style: {
          display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0,
          background: 'var(--dsw-alias-bg-base)',
          color: 'var(--dsw-alias-label-primary)',
          fontFamily: 'var(--dsw-font-family, system-ui, -apple-system, "Segoe UI", sans-serif)',
          fontSize: 12, overflow: 'hidden',
        },
      },
      h('style', null, CSS),
      h('div', {
        style: {
          flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8,
          padding: '10px 12px',
          borderBottom: '1px solid var(--dsw-alias-border-l1)',
        },
      },
      h(Logo, { size: 19 }),
      h('div', { style: { flex: 1, minWidth: 0 } },
        h('div', {
          style: {
            fontSize: 13.5, fontWeight: 650,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          },
        }, t('title')),
        h('div', {
          style: {
            marginTop: 1, fontSize: 10.5,
            color: 'var(--dsw-alias-label-secondary)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          },
        }, data
          ? `${modeLabel(data.transport?.mode, t)}${data.transport?.baseUrl ? ` · ${data.transport.baseUrl}` : ''}`
          : t('description'))),
      data?.console?.url
        ? h(LinkButton, { href: data.console.url, label: t('openConsole'), compact: true })
        : null,
      h('button', {
        type: 'button', className: 'ofu-btn', onClick: refresh, disabled: loading,
        title: t('refresh'), 'aria-label': t('refresh'),
        style: {
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 27, height: 27, padding: 0, borderRadius: 7,
          border: '1px solid var(--dsw-alias-border-l1)',
          background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
          cursor: loading ? 'default' : 'pointer',
        },
      }, h('span', {
        style: {
          display: 'inline-flex',
          animation: loading ? 'ofu-spin 0.8s linear infinite' : 'none',
        },
      }, h(RefreshIcon, { size: 14 })))),

      h('div', {
        className: 'ofu-scroll',
        style: { flex: 1, minHeight: 0, overflowY: 'auto' },
      },
      body,
      data?.refreshedAt
        ? h('div', {
          style: {
            padding: '0 12px 12px', fontSize: 10,
            color: 'var(--dsw-alias-label-secondary)',
          },
        }, `${t('lastUpdated')} ${formatTime(lastPolledAt || data.refreshedAt)}`)
        : null));
    }

    return {
      inject: ['betterSidebar', 'locale'],
      apply(ctx) {
        ctx.effect(() => {
          const disposers = [];
          for (const [locale, dict] of [
            ['en', EN], ['en-US', EN], ['zh', ZH], ['zh-CN', ZH],
          ]) {
            try {
              disposers.push(ctx.locale.register('openfuyao', locale, dict));
            } catch (error) {
              // A hot reload can re-run apply before the previous fiber's
              // dictionaries are disposed; an existing dictionary is already
              // the text this namespace needs.
              if (!/duplicate|already/i.test(String(error))) throw error;
            }
          }
          return () => {
            for (const dispose of disposers) dispose();
          };
        });

        ctx.effect(() => ctx.betterSidebar.registerTab({
          id: 'openfuyao:overview',
          title: () => text(ctx, 'title'),
          description: () => text(ctx, 'description'),
          icon: (size) => h(Logo, { size }),
          order: 45,
          single: true,
          component: Panel,
        }));
      },
    };
  },
});
