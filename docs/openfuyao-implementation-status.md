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

本机已在 KVM 快照 `snap-20261019` 后执行 `bke init`，结果见第 6 节。首次失败
暴露了 26.09 默认 cgroup v2 与 BKE k3s 的兼容问题，已通过切 cgroup v1 解决；
这是 26.09 的部署前置条件，不是编排代码问题。

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

1. ~~配置模型并实例化 `openfuyao-deployer`~~ 已完成：生产库配置 `deepseek-flash`
   （默认模型），模板已实例化，模型链路实测可对话；
2. 在控制台完成阶段 2（单节点业务集群）与阶段 3（应用市场 nginx）；
3. 记录 26.09 的兼容性偏差与耗时，失败则按决策点回退 22.03。

## 6. 26.09 实机验证（2026-10-20）

前置调整：26.09 默认 cgroup v2 下，根 cgroup 的 `cgroup.controllers` 有 `cpu`，
但子 cgroup 无法启用，BKE 的 k3s 报 `failed to find cpu cgroup (v2)` 并重启循环。
内核参数改为 `systemd.unified_cgroup_hierarchy=0` 后重启，确认：

```text
stat -fc %T /sys/fs/cgroup   -> tmpfs（混合模式）
/sys/fs/cgroup/cpu/cpu.cfs_quota_us -> -1
```

实跑结果（BKE `latest`，k3s v1.25.16+k3s4）：

- `bke preflight init` 仅 OS/内核矩阵失败，按 `OPENFUYAO_ALLOW_UNSUPPORTED_OS=true`
  继续；`bke init` 约 4 分钟完成，出现 `BKE initialization is complete`；
- 控制台 `:30010` 直连返回 302 到 OAuth；Pod 全部 Running/Completed；
- 通过后端 API + CLI 走通完整链路：预检 → 安装 BKE → `bke init` → 等待控制台 →
  `status=ready / phase=done`，CLI 退出码 0；
- 真实控制台经 Nginx `:3002` 访问：登录页 HTTP 200，标题 `openFuyao管理平台`；
  `X-Frame-Options` 已剥离，CSP `frame-ancestors` 含前端源，Cookie 无 `Secure`；
- 浏览器（Playwright，1680x1050）实测：选中冒烟 Agent → 展开工具面板 → `openFuyao`，
  右侧 iframe 加载真实 `欢迎登录 openFuyao` 页面，环境显示“已就绪 / 已连接”。

权限模型：后端以 `witty-service` 运行，Runner 对 `bke`、`kubectl` 和下载脚本使用
`sudo -n`；部署机需有对应 sudoers：

```sudoers
witty-service ALL=(root) NOPASSWD: /usr/local/bin/bke, /usr/bin/kubectl, /usr/bin/bash /var/lib/witty-service/.witty/openfuyao/*/download.sh
```

同时修复了非 root 下用 `bind` 探测 80/443 导致的误报，改为读
`/proc/net/tcp{,6}` 的 LISTEN 端口。

当前环境：`f39868ab-ac99-4bf9-a5ac-c27e2d0f0d82`，`console=https://192.168.122.146:30010`，
`proxy=http://192.168.122.146:3002/`，`status=ready`。该环境已从冒烟 Agent 转移到真实
`openfuyao-deployer`（`46083619-6933-440c-92c4-ae8570bc003b`，模型 `deepseek-flash`），
冒烟 Agent 已删除。工作目录按 environment_id 划分，转移不涉及目录搬迁。

### 6.1 初始化模板报 500 的修复

现象：智能体模板初始化返回 500，日志末行为
`PermissionError: [Errno 13] Permission denied: .../agent-workspaces/<uuid>`。

根因：`.witty/agent-workspaces` 曾被 root 创建（`root:root`），而 backend 以
`witty-service` 运行，无权在其中新建 Agent 目录。属 bug 之外的环境状态问题。

```bash
chown -R witty-service:witty-service /var/lib/witty-service/.witty/agent-workspaces
```

预防：`/etc/systemd/system/witty-backend.service.d/workspace-perms.conf` 用
`ExecStartPre=+/usr/bin/install -d -o witty-service -g witty-service -m 0755 ...`
在每次启动时校正属主（systemd 的 `StateDirectory=` 只覆盖顶层目录，不含子目录）。
系统化排障方法见 [troubleshooting-guide.md](troubleshooting-guide.md)。
