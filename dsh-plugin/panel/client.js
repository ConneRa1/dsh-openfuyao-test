/**
 * openFuyao right-sidebar panel.
 *
 * The module is a plain `window.__ModuleLoader__` factory, like the harness's
 * own client plugins, so the bundle needs no build step. It registers one tab
 * with dsh-better-sidebar; that plugin lands the tab in DSH's native right
 * Sidebar (and in its own + menu), so the panel is reachable without a second
 * application shell or an iframe.
 *
 * The tab is a read-only status view: what is installed for this agent, which
 * business clusters and applications exist, and how to reach the console.
 */

window.__ModuleLoader__.load({
  id: '@openwitty/dsh-openfuyao-panel',
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

    function loadEnvironments(signal) {
      return fetchJson('openfuyao/api/environments', { signal });
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

    function Panel(props) {
      const t = (key) => text(props.ctx, key);
      const [state, setState] = React.useState({ phase: 'loading', data: null, error: null });
      const [requestId, setRequestId] = React.useState(0);
      const [lastPolledAt, setLastPolledAt] = React.useState(null);
      const visible = props.visible !== false;
      const requestRef = React.useRef(0);
      // One latch keeps a slow backend (30 s timeout) from stacking ticks.
      const pollInFlight = React.useRef(false);

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
            setLastPolledAt(payload.refreshedAt || new Date().toISOString());
            setState((previous) => (previous.data
              ? { ...previous, data: { ...previous.data, environments } }
              : previous));
          }).catch(() => {
            // A failed poll keeps the last known state on screen and the
            // next tick retries.
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

      const environment = Array.isArray(data?.environments)
        ? data.environments[0]
        : null;
      const ready = environment?.status === 'ready';

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
          h('div', {
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
