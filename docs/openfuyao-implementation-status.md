# openFuyao MVP 实施状态与验证记录

> 分支：`feat/openfuyao-mvp`（`witty-service` / `polymind`，均从 `master` 起）
> 日期：2026-10-19
> 范围：Phase 0 自动门禁 + Phase 1 后端编排 + Phase 2 Nginx/前端面板。

---

## 1. 分支与文档

- 后端：`feat/openfuyao-mvp`，备份分支 `backup/openfuyao-poc-20261019`；
- 前端：`feat/openfuyao-mvp`，备份分支 `backup/openfuyao-poc-20261019`；
- 未跟踪文档/模板已按主题提交：`GLOSSARY.md`、`docs/adr/0001`、评估稿、
  MVP 方案、宿主机回退 runbook、`openfuyao-deployer` 模板。

## 2. Phase 0：环境与兼容性门禁

自动门禁通过（0 fail / 3 warn）：

```bash
cd /root/witty-service
witty-service openfuyao preflight
# 或
.venv/bin/python -m witty_service.openfuyao_cli preflight
```

实测：openEuler 26.09 / aarch64 / 8C / 14.5 GiB / 可用 94.4 GiB；
Docker/K8s 残留与 30010/6443/80/443 端口均通过；OBS、镜像仓库、应用市场可达；
NTP 未同步。完整记录见
[openfuyao-phase0-compatibility.md](openfuyao-phase0-compatibility.md)。

**未执行**：`bke init` 与完整快速入门（阶段 1/2/3）。原因：本机是活动开发机，
`bke init` 会安装 k3s/containerd 并调整网络/NTP，必须先在 KVM 快照后执行。
验收机仍需按 Phase 0 文档完成端到端手工确认。

## 3. Phase 1：后端编排

已落地：

| 能力 | 位置 |
| --- | --- |
| Environment 表/迁移/仓储 | `persistence/openfuyao_repository.py`、`alembic/versions/20261019_01_*` |
| 状态机/并发/取消/日志游标 | `application/openfuyao/environment_service.py` |
| 宿主机快检 | `application/openfuyao/preflight.py` |
| BKE 下载校验/init/控制台轮询 | `application/openfuyao/bootstrap_runner.py` |
| 控制台健康检查 | `application/openfuyao/console_health.py` |
| REST API | `api/openfuyao.py`（`/openfuyao/environments...`） |
| Agent 入口 | `witty-service openfuyao deploy/status/cancel/logs` |
| 面板联动 | `openfuyao.open` 信号事件 + 历史 payload 保留 |

关键约束：

- 一宿主一 Environment（`host` 唯一）；同一环境同时只允许一个 Bootstrap；
- `POST /bootstrap` 必须 `confirm: true`；取消按进程组回收；
- 服务重启把 `bootstrapping/waiting_console` 标记为 `BOOTSTRAP_INTERRUPTED`；
- 日志落 `<workspace>/openfuyao/<env>/bootstrap.log`，API 按字节游标读取。

验证：

```bash
cd /root/witty-service
.venv/bin/python -m pytest -q
# 1809 passed, 12 skipped
```

实际启动临时 API + CLI 走通：`deploy --dry-run` → `deploy`（预检并落库）→
`status` → `logs` → `cancel`；鉴权 401、Host 冲突 409、控制台不可达均符合预期。

## 4. Phase 2：Nginx + 前端

- `install-local.sh` 增加 3002 server block：`proxy_hide_header X-Frame-Options` /
  `Content-Security-Policy`，重写 CSP、`proxy_cookie_flags ~ nosecure samesite=lax`，
  支持 WebSocket/SSE 与 `proxy_redirect`；
- `start.sh` 生成 `OPENFUYAO_PROXY_PORT` / `OPENFUYAO_CONSOLE_UPSTREAM` /
  `FRONTEND_ORIGIN`，启动前校验端口，启动后探活 `/__of_health`；
- 前端按 Agent 拉取 Environment，展示预检/进度/日志/失败原因；ready 后只加载代理
  iframe；阶段 2/3 只做人工确认，不伪造自动状态。

Nginx 已用本机 nginx 1.30.4 验证：

```text
nginx: configuration file ... syntax is ok
nginx: configuration file ... test is successful
```

并用自签 HTTPS 假控制台验证：上游 `X-Frame-Options` 被剥离、CSP 被替换为
`frame-ancestors 'self' <frontend-origin>`、`Secure` Cookie 被改为
`HttpOnly; SameSite=Lax`、上游 302 Location 拉回代理。

前端验证：

```bash
cd /root/polymind
pnpm test        # 376 passed
pnpm typecheck   # pass
pnpm build       # pass
```

## 5. 仍需人工完成的验收

1. 干净 8C/16G / 可用 ≥100 GiB / openEuler 26.09 机器，快照后执行 `bke init`；
2. 确认 `BKE initialization is complete`、Pod 全部 Running/Completed；
3. 浏览器打开面板，确认 iframe 显示登录页、可登录、刷新不掉；
4. 在控制台完成阶段 2（单节点业务集群）与阶段 3（应用市场 nginx）；
5. 记录 26.09 的兼容性偏差与耗时，失败则按决策点回退 22.03。
