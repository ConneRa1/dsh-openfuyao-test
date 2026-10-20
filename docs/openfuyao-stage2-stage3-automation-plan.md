# openFuyao 阶段 2/3 自动化实施方案（Agent-first · 桌面端承载）

> 修订说明：
> 1. 上一版从“后端能力”出发、以 Shell 跑通为验收，偏离“用 agent 自动化部署”的需求；本版以
>    **PolyMind 中 `openfuyao-deployer` agent 的实际产品能力**为核心。
> 2. 本版把**承载端从 Web 改为 PolyMind 桌面端（Electron）**：右侧面板、控制台窗口、验收会话
>    都在桌面端完成；Web 只保留为调试/兜底，不再作为验收路径。
> 3. VS Code 端口转发相关的 iframe 改写（提交 `e7f8e5d`）已撤回。
>
> 输入：`openfuyao-stage2-stage3-run-20261020.md`（阶段 2/3 实跑与事故记录）
> 状态：阶段 1 已由 agent 跑通；桌面端已打包可点击启动；阶段 2/3 后端能力待实现。

---

## 1. 核心原则

1. **验收主体是 PolyMind 里的 agent，不是操作员**。每个阶段的“完成”必须有：
   - agent 会话 ID + 完整 tool call 链；
   - 用户在桌面端 UI 里只发一句自然语言；
   - 右侧面板状态正确、控制台在面板内可直接登录；
   - 最终可访问的 URL。
2. **agent 只做编排与确认，特权操作留在后端**。改 hostname、清 `/etc/kubernetes`、跑 `bke`、装 chart
   都由 `witty-service` 的 runner 以受控方式执行；agent 不直接拿 root shell。
3. **能力缺口优先补在 agent 侧**：CLI 输出要可解析、错误码要可解释、破坏性操作要二次确认、
   失败要给出下一步命令。后端接口设计服从这些约束。
4. **桌面端是唯一验收载体**：不要求 nginx/Next 运行；控制台用 `<webview>` 内嵌在右侧面板，不再另开窗口。

---

## 2. Agent 与承载端现状（事实基线）

| 项 | 现状 | 对自动化的影响 |
| --- | --- | --- |
| Agent | `openfuyao-deployer`（DB 中已存在） | 唯一部署 agent |
| Runtime | opencode，内置 bash `allow-all` | 可执行 CLI，但权限受沙箱用户限制 |
| 沙箱 | docker/local_process，服务用户 `witty-service`（docker 组） | 无宿主机 root；`/root/.openfuyao`（700）不可读 |
| sudo | `NOPASSWD: /usr/local/bin/bke, /usr/bin/kubectl, /usr/bin/bash /var/lib/witty-service/.witty/openfuyao/*/download.sh` | 阶段 1 够用；阶段 2/3 需要扩白名单或改走后端 |
| 环境变量 | 注入 `WITTY_AGENT_ID`；`AUTH_TOKEN` 继承服务进程 | CLI 能直接调本机 `127.0.0.1:8000` |
| Skill | 6 个远端 skill（ssh/kubernetes/openfuyao-cluster-deploy/openfuyao-app-install/openfuyao-node-os-setup/experience） | 阶段 2/3 的 skill 存在，但只是“命令行说明”，没有后端能力 |
| MCP | 模板未声明 | 工具面只有 bash；新增能力优先走 CLI，MCP 可选 |
| Prompt | 仍写“业务集群与应用市场安装由用户在官方控制台手动完成” | **阶段 2/3 不能 agent 化的直接原因**，需与后端同批修改 |
| 承载端 | PolyMind 桌面端（Electron，`app://polymind` 自包含） | 不依赖 nginx/Next；控制台在面板内嵌、直连 30010 |
| 已证实的 agent 能力 | 阶段 1 部署已由 agent 完成（环境 `ready/100%`） | CLI 链路可用，缺的是阶段 2/3 能力与 prompt 授权 |

结论：**阶段 2/3 的瓶颈不是“agent 不会用”，而是“后端没有可调用的能力 + prompt 禁止”**。

---

## 3. 目标链路

```text
用户在 PolyMind 桌面端右侧面板发一句话
        │
        ▼
openfuyao-deployer agent（opencode + bash + skills）
        │  只调用 CLI（--json 输出）
        ▼
witty-service CLI  ──HTTP──▶  witty-service API
                                   │
                                   ▼
                        openfuyao/*_service.py（状态机、记录）
                                   │
                                   ▼
                        openfuyao/*_runner.py（受控执行）
                          ├─ bke preflight / cluster create（sudo 白名单）
                          ├─ kubectl（sudo 白名单）
                          ├─ helm（后端直接执行，非 agent）
                          └─ 应用市场 API（只读解析）
                                   │
                                   ▼
                        日志 / progress / 错误码 ──▶ agent 汇报 + 桌面面板
                                   │
                                   ▼
                        控制台：右侧面板内嵌 <webview>（https://127.0.0.1:30010）
```

关键边界：

- agent **不**直接 `bke cluster create`、**不**直接改 hostname、**不**读节点密码；
- 后端 runner 以 systemd 服务身份运行，通过 sudoers 白名单执行特权命令；
- 节点密码由用户在后端配置（环境变量/凭据文件，`witty-service` 可读），不经过 agent 上下文。

### 3.1 桌面端承载

- 形态：`app://polymind` 托管 `desktop/renderer/` 静态导出，主进程代理 `/api → 127.0.0.1:8000`；
  **不需要 nginx，也不需要 Next 服务端**，只要求 `witty-backend` 在 8000。
- 控制台：桌面端用 `<webview>` **内嵌在右侧面板**，视觉和 Web 端 iframe 一致，但不是跨站 iframe。
  控制台 Cookie 是 `Secure; SameSite=Lax/Strict`，在 `app://polymind` 的跨站 iframe 里不会随子请求发送；
  `<webview>` 是独立的 guest webContents（按顶层框架加载），SameSite Cookie 正常。
  - 主进程 `will-attach-webview` 校验 src 只允许控制台端口，剥掉 preload/Node，固定 `persist:polymind-console` 分区；
  - 只对控制台端口放行自签证书；guest 在控制台端口上的 https 跳转放行，外链仍交系统浏览器；
  - 面板宽度小于控制台设计宽度时整体缩放，避免横向裁切；
  - 不再需要 preload/IPC 开关，Web 端保留原 iframe 路径。
- 启动：`/usr/local/bin/polymind-desktop` → `/opt/polymind-desktop-linux-arm64/polymind-desktop`；
  root 下自动追加 `--no-sandbox`（Electron 的硬限制）；桌面项 `StartupWMClass=polymind-desktop`。
- 构建/重打包：
  ```bash
  cd /root/polymind/desktop && npm run build:renderer
  npx @electron/packager . polymind-desktop --platform=linux --arch=arm64 \
    --out=/opt --overwrite --asar=false --icon=assets/icon.png
  ```

---

## 4. Agent 接口契约（先定这个，再写后端）

### 4.1 CLI 命令

```bash
# 阶段 2（多节点契约见 §11.2）
witty-service openfuyao cluster create \
  --name bke-cluster \
  --node ip=192.168.122.146,hostname=auto-depoly,role=master \
  --node ip=192.168.122.151,hostname=node-2,role=worker \
  --confirm --wait --json
witty-service openfuyao cluster status --name bke-cluster --wait --json
witty-service openfuyao cluster logs --name bke-cluster --follow
witty-service openfuyao cluster destroy --name bke-cluster --confirm --json

# 阶段 3
witty-service openfuyao app install \
  --cluster bke-cluster --release nginx-demo --repo local --chart nginx \
  --version 25.2.5 --namespace default --confirm --wait --json
witty-service openfuyao app status --release nginx-demo --json
```

### 4.2 输出契约（agent 依赖）

- `--json` 输出稳定字段：`id/status/phase/progress/error_code/error_message/verify_url`；
- 非 0 退出码与 `error_code` 一一对应，agent 不需要解析人类可读文本；
- 失败时 `error_message` 必须包含“下一步动作”（例如“检查节点 hostname 是否符合 RFC 1123”）；
- 同一命令重复执行必须幂等：已 ready 的集群/已 deployed 的应用返回 0 并给出现有 URL。

### 4.3 确认协议

- `create`/`install` 不带 `--confirm` 时只做预检并打印影响面，退出码 2；
- 带 `--confirm` 才执行；agent 在调用前必须先向用户复述影响面（删/建/覆盖），得到明确同意；
- 取消：`cluster cancel`/`app cancel`，agent 可在用户改口时调用。

> **实施备注（2026-10-20，已落地，阶段 2/3 直接复用）**：退出码已收敛为
> `witty_service.domain.openfuyao.ExitCode`，并修正了原实现“不带 `--confirm` 返回 0”的偏差：
>
> | 码 | 含义 | 阶段 2/3 对应 |
> | --- | --- | --- |
> | 0 | 成功；**含幂等**（已 ready / 已在执行都返回 0） | 已 ready 的集群、已 deployed 的应用 |
> | 1 | 执行错误（参数、API 不可达、业务 4xx/5xx） | — |
> | 2 | 需要确认（预检通过但缺 `--confirm`；`--json` 带 `needs_confirm=true`） | `cluster create` / `app install` |
> | 3 | 预检未通过（未执行任何特权动作） | `Gate.node` 失败 |
> | 4 | 已到终态但不是目标态（`failed`/`cancelled`） | 创建超时、安装失败、用户取消 |
>
> 同时 `--json` 已改为**只输出一个文档**（deploy 为
> `{exit_code, needs_confirm, summary, environment, preflight, plan}` 信封），
> 新增子命令请复用 `openfuyao_cli._finish`，不要各自打印多段 JSON。

### 4.4 错误码（agent 可直接翻译给用户）

```text
HOSTNAME_INVALID        节点主机名不符合 RFC 1123
NODE_UNREACHABLE        SSH 不可达/凭据错误
MEMORY_INSUFFICIENT     内存 < 16 GiB
PREFLIGHT_FAILED        集群预检失败（details 带失败项）
CLUSTER_CREATE_TIMEOUT  创建超时（附 CR conditions 与 kubelet 日志末尾）
CHART_PULL_FAILED       chart 拉取失败（附已尝试的镜像源）
APP_VERIFY_FAILED       Pod/HTTP 验证失败
CONFLICT_EXISTS         同名资源已存在且不可复用
CANCELLED               用户取消
```

---

## 5. 后端能力（服务于上面的契约）

### 5.1 领域模型

> **2026-10-20 修订**：单节点字段（`node_ip/node_hostname/role`）改为 1:N 节点表。
> 多节点契约、错误码映射与边界见 [§11](#11-阶段-2-多节点方案定稿2026-10-20)。

```text
openfuyao_clusters: id, environment_id, agent_id, name, namespace,
  status/phase/progress, expected_node_count, kubeconfig_path, endpoint,
  preflight_json, error_code, error_message, timestamps

openfuyao_cluster_nodes: id, cluster_id, ip, hostname, port, username,
  role, is_local, status, phase, error_code, last_message, timestamps
  —— 节点密码**不入库**，只存主机侧凭据文件引用

openfuyao_apps: id, cluster_id, agent_id, namespace, release_name,
  repo_name, chart_name, chart_version, values_json, image_override,
  status/phase/progress, node_port, verify_url, error_code, error_message, timestamps
```

状态机：

```text
Cluster: pending → preflight → creating → joining → waiting_ready → ready
                                  ↘ failed / cancelled
Node:    pending → preflight → bootstrapping → joined → ready
                                  ↘ failed（error_code + last_message 归因到该节点）
App:     pending → resolving → installing → verifying → deployed
                                  ↘ failed / cancelled
```

复用阶段 1 的 runner 模式：独立进程组、日志落盘、进度回调、取消即回收、启动时恢复中断记录。

### 5.2 阶段 2 执行器

> 多节点（本地 master + N 台已有节点）的定稿流程与错误映射见
> [§11](#11-阶段-2-多节点方案定稿2026-10-20)。下面是不随节点数变化的骨架。

1. 校验 environment ready、管理 k3s（`/etc/rancher/k3s/k3s.yaml`）可连；
2. 解析节点清单（本地节点 + 调用方给出的已有节点）：hostname RFC 1123、IP/hostname 去重、
   角色拓扑（本期恰 1 个 master）、凭据可解析；
3. 渲染 `bkecluster.yaml`/`bkenodes.yaml`（单文件多文档，0600，密码来自主机侧凭据文件，
   目录在 `<work_dir>/<cluster_id>/`，执行后删除）；
4. `bke preflight cluster-create --output json`（**实测有稳定 JSON，退出码 3 = 预检失败**）：
   逐条 `results[]` 映射错误码；仅 OS/内核矩阵失败且开关打开时继续并记录例外；
5. `bke cluster create -f/-n`：退出码非 0 不立即判失败，转 CR 轮询；
6. 轮询 `BKECluster`/`BKENode` + `kubectl get nodes`，直到 `ClusterReady/Healthy`
   **且节点数与预期一致、全部 Ready**；
7. 失败分类：hostname/静态 Pod、内存/CPU/磁盘、端口、镜像拉取、超时，并**归因到具体节点**；
8. `recreate`/`destroy` 时受控清理：只删本集群 CR（等 finalizer 走完），**禁止 `bke reset`**；
   删 CR 不会清理节点运行时，必须把 `nodes_dirty` 回报给调用方（实测见 §11.1 D7）。

### 5.3 阶段 3 执行器

1. 应用市场 API 解析 repo/chart/版本（只读，不做 OAuth 写操作）；
2. `helm upgrade --install` 安装/升级，注入 image override 与 values；
3. OCI 拉取失败时兜底：镜像源拉 chart → 上传 local harbor → 同步 `local` 仓库 → 换 repo 重装；
4. 验证：Pod Ready、Service NodePort、HTTP 预期状态码；成功记录 `verify_url`；
5. 失败保留现场；显式 `rollback` 才 `helm rollback`。

---

## 6. Agent 侧改造（与后端同批交付）

### 6.1 Prompt

删除：“业务集群与应用市场安装由用户在官方控制台手动完成，不要声称已自动完成。”

改为：

```text
阶段 2/3 统一走后端编排 CLI，禁止直接 bke/helm 操作：
  witty-service openfuyao cluster create ... --confirm --wait --json
  witty-service openfuyao app install ... --confirm --wait --json
调用前必须先向用户确认影响面；失败按 error_code 给出下一步；不要绕过预检。
控制台只用于展示与人工兜底，不是执行通道。
```

### 6.2 Skill

- `openfuyao-cluster-deploy`：从“bke 命令手册”改为“调用 cluster create + 轮询 + 错误码处理”；
- `openfuyao-app-install`：从“helm 命令手册”改为“调用 app install + 验证 + OCI 兜底说明”；
- 两个 skill 都要求先读 `witty-service openfuyao ... --help`，避免硬编码参数。

### 6.3 工具面

- 首版只保留 bash（已有 `allow-all`），CLI 即工具；
- MCP 工具作为后续增强（`openfuyao_cluster_create`/`openfuyao_app_install`），不阻塞首版。

### 6.4 权限

- sudoers 只需保留 `bke`、`kubectl`；`helm` 由后端直接执行，不暴露给 agent；
- 节点密码放 `/var/lib/witty-service/.witty/openfuyao/node.cred`（witty-service 可读，0600），
  不再放 `/root/.openfuyao`；
- 环境变量补 `OPENFUYAO_ENABLE_NTP=false`、`OPENFUYAO_ALLOW_UNSUPPORTED_OS=true`。

---

## 7. 验收（只认桌面端 agent 会话）

| # | 用户在桌面端发的话 | 期望 agent 行为 | 通过标准 |
| --- | --- | --- | --- |
| A1 | “帮我部署一套 openFuyao 环境，完成后打开右侧面板” | `witty-service openfuyao deploy --confirm` → `status --wait` → 写 console signal | 控制台 303 → 登录页；面板显示 ready；transcript 含上述调用 |
| A2 | “在这台机器上创建一个单节点业务集群，节点 192.168.122.146” | 先复述影响面并等确认 → `cluster create ... --confirm --wait --json` → 汇报 endpoint | `BKECluster` Healthy；控制台集群列表可见；transcript 无手工 bke |
| A3 | “从应用市场给业务集群装一个 nginx，用 NodePort 暴露” | `app install ... --confirm --wait --json` → 汇报 URL | Pod Running；`curl <node>:<port>` 200；控制台应用管理可见 |
| A4 | “集群创建失败了，帮我看看” | `cluster status --json` → `cluster logs` → 按 error_code 给下一步 | 回答能定位到 hostname/内存/端口/镜像之一，不瞎猜 |

补充门槛：

- 桌面端控制台必须内嵌在右侧面板、能完成登录（凭据由用户提供，不要猜测默认密码），不依赖 nginx/3002 网关；
- transcript 中不得出现 agent 直接 `bke cluster create`、`helm install`、`useradd`、`/etc/kubernetes` 操作；
- 同一 prompt 重复发送不产生第二个集群/release；
- 失败场景必须给出可执行下一步，而不是“请检查日志”。

> 多节点（本地 master + 已有节点）的补充验收 **A2b–A2e** 见 §11.7。

---

## 8. 实施顺序（每阶段以桌面端 agent demo 收尾）

| 阶段 | 内容 | 交付证据 |
| --- | --- | --- |
| A | 抽 `process.py`/`kube.py`；阶段 2 runner + 单测 | 单测通过 |
| B | 阶段 2 service/API/CLI（`--json`/`--confirm`/幂等） | A2 桌面会话通过 |
| **B′** | **多节点**：节点表 + 多文档渲染 + 预检 JSON 映射 + 节点级失败归因 | ✅ 2026-10-20 实跑通过（A2b）；A2c/A2d 负例退出码已验证 |
| C | 阶段 3 runner/service（OCI 兜底） | 单测通过 |
| D | 阶段 3 API/CLI | A3 桌面会话通过 |
| E | prompt/skill 更新 + 文档 | A1/A4 桌面会话通过 |
| F | 负例与全量回归（reset → A1 → A2 → A2b → A3） | 四轮 transcript |

工期：后端 ~8 天，含 prompt/skill/前端 ~12 天；多节点（B′）**追加 ~4 人日**（已扣除 SSH 采集与
paramiko 依赖——实测由 `bke preflight` 承担）。

---

## 9. 本次已执行的操作（2026-10-20）

1. 用户已在 VM 管理面打快照；
2. 执行 `bke reset --all --mount --confirm`（15:24:48 完成，日志 `/var/log/openfuyao/reset-20261020-1516.log`）；
3. 重启 `witty-backend`（8000），补 `OPENFUYAO_ENABLE_NTP=false`、`OPENFUYAO_ALLOW_UNSUPPORTED_OS=true`、`OPENFUYAO_KUBECONFIG=/etc/rancher/k3s/k3s.yaml`；
4. 把 DB 遗留 environment 记录置为 `failed`，避免 agent 误判；阶段 1 已由 agent 跑通（`ready/100%`，控制台 303）；
5. **桌面端落地**：
   - 撤回端口转发适配（`git revert e7f8e5d`），不再让 iframe 跟随页面 host；
   - Electron 壳改用 `<webview>` 内嵌控制台：主进程校验 src、剥 preload/Node、固定 `persist:polymind-console` 分区；
   - 只对控制台端口放行自签证书；面板内自适应缩放；Web 端保留 iframe；
   - 修复此前“点打开控制台没反应”：按钮把 3002 网关地址传给了只接受 30010 的 IPC，现改为面板内嵌；
   - `npm run build:renderer` + `@electron/packager` 打包到 `/opt/polymind-desktop-linux-arm64`，
     启动器 `/usr/local/bin/polymind-desktop`、桌面项 `/usr/share/applications/polymind.desktop`；
   - 已验证：`app://polymind` 安全上下文、`/api/agents` 200、页面零错误；控制台在右侧面板内
     渲染登录页（自签证书被定向放行，无横向裁切）；
6. 当前 Web 栈（nginx 3000/3002 + Next 3001）仍可作兜底，但桌面端不依赖它。

---

## 10. 待确认

1. ~~节点密码的交付方式~~ → **已定**：主机侧凭据文件 `nodes.cred`（0600，按 IP 索引），
   agent 只传 ip/hostname/port/user/role，见 §11.1 D3。
2. 阶段 2 是否允许 agent 在用户未明确说“创建”时只做预检（推荐：是）。
3. ~~应用市场安装是否必须走控制台 API~~ → **已定**：首版走 `helm upgrade --install`，
   市场里能看到同一 release（实跑已确认）；接 marketplace REST 留作后续。

---

## 11. 阶段 2 多节点方案定稿（2026-10-20）

> 依据：`docs/openfuyao-multinode-spike-findings.md`（2026-10-20 实测：多文档预检、JSON 契约、
> `bke cluster scale` 未注册、`--hostname-override`、删 CR 不清理节点）。
> 状态：**已实现并实跑通过（2026-10-20）**，证据见
> `docs/openfuyao-stage2-multinode-run-20261020.md`；落点见 §11.10。

### 11.1 决议（D1–D8）

| # | 决议 | 依据 |
| --- | --- | --- |
| **D1** | 支持范围：**建集群时**指定“本地 1 台 master(etcd) + N 台已有节点(worker)”；**不做**多 master/HA；**不做**建好后扩容 | `bke cluster scale` 未注册（实测）；`bke cluster --help` 只有 `create/list` |
| **D2** | 节点名 = `spec.hostname`，由调用方给定；BKE 用 `--hostname-override` 注册 kubelet，**不改 OS hostname、不校验 RFC1123** → 本地必须校验 | bkeagent 日志实测 |
| **D3** | 凭据只存在主机侧 `nodes.cred`（0600，按 IP 索引，含本地节点）；agent 上下文**永不含密码** | 方案 §3 边界 |
| **D4** | 四层校验：L1 本地纯函数（hostname/IP/角色/去重）→ L2 `bke preflight cluster-create --output json` → L3 创建后 CR 轮询 → L4 `kubectl get nodes` 数量+Ready | 实测 JSON 契约 |
| **D5** | 错误码：复用 `NODE_UNREACHABLE`/`HOSTNAME_INVALID`/`MEMORY_INSUFFICIENT`/`CONFLICT_EXISTS`，新增 8 个（§11.5） | `ErrorCode` 只增不改 |
| **D6** | 幂等：同 name + **同节点集** → 退出 0 返回现有；同 name + 不同节点集 → `CONFLICT_EXISTS`；进行中 → 跟随等待 | 方案 §4.2 |
| **D7** | 失败/销毁：只删 `BKECluster`（等 finalizer），**不做远端清理**；返回 `nodes_dirty` 列表与“请重装该节点”的下一步 | 实测：删 CR 后控制面仍在跑 |
| **D8** | 禁止直接删 master 的 `BKENode`（webhook 拒绝），只能删 `BKECluster`；自动化里同样**禁止** `bke reset` | 实测 webhook + 本轮 reset 事故 |

### 11.2 契约

```bash
# 建集群：本地 master + 1 台已有 worker
witty-service openfuyao cluster create --name bke-multi \
  --node ip=192.168.122.146,hostname=auto-depoly,role=master \
  --node ip=192.168.122.151,hostname=node-2,role=worker \
  --confirm --wait --json

# 多节点用文件（不含密码），凭据仍按 IP 从 nodes.cred 取
witty-service openfuyao cluster create --name bke-multi \
  --nodes-file nodes.json --confirm --wait --json

# 销毁（只删 CR，回报节点残留）
witty-service openfuyao cluster destroy --name bke-multi --confirm --json
```

- `--node` 可重复，`key=value` 形式，**顺序无关**；允许键：`ip`(必填) `hostname`(必填)
  `role`(`master|worker`，默认 worker) `port`(默认 22) `username`(默认取凭据文件)；
- 本地节点可省略：默认取 environment 的宿主 IP/hostname；
- `--json` 信封复用现有 `_finish`：
  `{exit_code, needs_confirm, summary, cluster, nodes[], preflight, plan}`；
  `summary` 必须回显节点表，供 agent 向用户复述影响面；
- 退出码沿用 `ExitCode`：0 成功/幂等、1 执行错误、2 需确认、3 预检未过、4 终态非目标。

### 11.3 数据模型

```text
openfuyao_clusters
  id, environment_id, agent_id, name, namespace,
  status, phase, progress, expected_node_count,
  kubeconfig_path, endpoint, preflight_json,
  error_code, error_message, created/updated/started/finished

openfuyao_cluster_nodes
  id, cluster_id, ip, hostname, port, username, role, is_local,
  status, phase, error_code, last_message, created/updated
  UNIQUE(cluster_id, ip), UNIQUE(cluster_id, hostname)
```

- `role` 存 `master|worker`，渲染时展开为 BKE 的 `["master/node","etcd"]` / `["node"]`；
- 进度按阶段映射（`build_plan` 复用）：`preflight 10 → render 15 → submitted 30 →
  control_plane 55 → joining 75 → wait_ready 90 → done 100`；
- 中断恢复：集群处于 `creating/joining/waiting_ready` 且无 runner → `CLUSTER_INTERRUPTED`。

### 11.4 执行流程

```text
resolve env(ready) + mgmt kubeconfig
  → L1 节点校验（hostname RFC1123 / IP 格式 / 双唯一 / 恰 1 master / 本地节点存在）
  → 解析凭据（缺 → NODE_CREDENTIAL_MISSING，不进入执行）
  → 渲染 cluster.yaml + nodes.yaml（0600，<work_dir>/<cluster_id>/，finally 删除）
  → bke preflight cluster-create --output json（超时 10m）
        FAIL → 逐条映射（§11.5），cluster failed，退出 3，不执行 create
  → bke cluster create（超时 25m）
        退出码非 0 不判死，转 CR 轮询
  → 轮询 BKECluster.conditions[ClusterReady/Healthy] + 每台 BKENode.conditions
  → kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes
        要求 count == expected_node_count 且全 Ready
  → ready：写 endpoint/kubeconfig_path，nodes 全部 ready
```

失败归因优先级：`BKENode.conditions` 里失败的那台 → 该节点 `status=failed` + `last_message`；
集群级错误落 cluster。镜像拉取类超时额外附 `kubectl describe node`/Pod 事件末尾。

### 11.5 错误码映射（L2 实测字段 → 我们的码）

| `ruleID` | 新增/复用 `ErrorCode` |
| --- | --- |
| `CLUSTER-SSH-TRANSPORT`、`CLUSTER-SSH-AUTH` | `NODE_UNREACHABLE`（复用） |
| `CLUSTER-SSH-PRIVILEGE` | `NODE_PRIVILEGE_MISSING`（新增） |
| `CLUSTER-RES-MEMORY` | `MEMORY_INSUFFICIENT`（复用） |
| `CLUSTER-RES-CPU` | `NODE_CPU_INSUFFICIENT`（新增） |
| `CLUSTER-RES-SYSTEM-DISK` | `NODE_DISK_INSUFFICIENT`（新增） |
| `CLUSTER-PLAT-DISTRO`、`CLUSTER-PLAT-KERNEL` | `PREFLIGHT_FAILED`（26.09 例外走白名单开关） |
| `CLUSTER-PORT-*`、`CLUSTER-SRC-REACHABLE`、其余 | `PREFLIGHT_FAILED`（details 带 ruleID/subject/actual/remediation） |
| 本地 hostname 校验 | `HOSTNAME_INVALID`（复用，**BKE 不查，必须我们自己查**） |
| 凭据缺失 | `NODE_CREDENTIAL_MISSING`（新增） |
| 集群级拓扑/唯一性（`CLUSTER-TOPO-*`/`UNIQUE-*`） | `NODE_ROLE_INVALID`（新增） |
| 创建后节点数不符 / 有节点非 Ready | `NODE_COUNT_MISMATCH` / `NODE_NOT_READY`（新增） |
| 同名不同节点集 | `CONFLICT_EXISTS`（复用） |
| 中断 | `CLUSTER_INTERRUPTED`（新增） |

> 新增码共 8 个；`ErrorCode` 只增不改，历史消息不受影响。

### 11.6 前端（右侧面板）

- 节点表格：本地节点固定一行（不可删），已有节点行内编辑 `IP/主机名/角色`，支持增删；
- 每行显示 `status/phase/error_code/last_message`；集群级显示总体进度与端点；
- 预检失败时把 `remediation` 原文展示（可直接照抄给用户）；
- 销毁按钮二次确认，确认框里列出**将被残留的节点**（`nodes_dirty` 预览）。

### 11.7 验收（在 A2 之外新增）

| # | 用户话术 | 期望 | 通过标准 |
| --- | --- | --- | --- |
| A2b | “用 192.168.122.151 这台机器作为第二个节点，建一个集群” | 先复述节点表并确认 → `cluster create --confirm --wait --json` | `kubectl get nodes` 2 台全 Ready；`BKENode` 2 条；控制台集群详情可见 2 节点 |
| A2c | 同上，但 hostname 写成 `node_2` | 本地预检直接退出 3，`HOSTNAME_INVALID` | 未执行 `bke cluster create`；文案给“改成 RFC1123 后重试” |
| A2d | 节点 IP 未配置凭据 | `NODE_CREDENTIAL_MISSING`，退出 1 | 不渲染 yaml、不落库为 failed 之外的中间态 |
| A2e | 销毁后询问节点状态 | 回答“CR 已删，但节点仍保留 kubelet/控制面”并给清理清单 | 不声称“已回退干净” |

### 11.8 明确不做

- 多 master / etcd HA（模板存在，但证书、故障面、验收成本都不成比例）；
- 建好后的 scale-up（依赖未注册的 `bke cluster scale` 或未验证的直接建 CR）；
- 远端节点自动清理/`bke reset`（runbook 禁止）；
- 面板里输入节点密码（凭据走主机侧文件）。

### 11.9 仍需你拍板（3 个，默认值已给）

1. 远端节点是否允许当 master？**默认否**（本期只 worker）。
2. 是否允许“不要本地节点、全部用已有机器”？**默认否**（镜像仓库/控制台在本机 AIO 上，跨机会引入新配置面）。
3. 凭据文件沿用 `nodes.cred`（YAML，按 IP 索引）？**默认是**；如偏好环境变量或 Vault，现在改成本最低。



### 11.10 实现落点（2026-10-20 已交付）

| 层 | 文件 | 说明 |
| --- | --- | --- |
| 领域 | `domain/openfuyao.py` | Cluster/Node/App 状态、阶段进度、8 个新错误码 |
| 节点清单 | `application/openfuyao/cluster_spec.py` | `--node` 解析、RFC1123/IP/唯一性/角色拓扑、BKENode 多文档 |
| 凭据 | `application/openfuyao/node_credentials.py` | `nodes.cred`（0600，按 IP 索引）；缺凭据直接 `NODE_CREDENTIAL_MISSING` |
| 渲染 | `application/openfuyao/cluster_render.py` | 已知可用的集群模板 + 按 master IP 替换仓库地址；0700/0600 落盘、finally 删除 |
| 执行 | `application/openfuyao/cluster_runner.py` | 预检 JSON → 错误码映射、`bke cluster create`、CR 轮询、`kubectl get nodes` 校验；OS/内核例外开关 |
| 服务 | `application/openfuyao/cluster_service.py` | 幂等/冲突/取消/销毁（只删 CR + `nodes_dirty`）、同步 `preflight` |
| 应用 | `application/openfuyao/app_runner.py`、`app_service.py` | `helm upgrade --install` + Pod/URL 验证；chart-dir / repo / OCI |
| 持久化 | `persistence/openfuyao_cluster_repository.py`、`orm.py`、`alembic/versions/20261021_01_*` | 三张表；密码不入库；启动时中断恢复 |
| API | `api/openfuyao.py`、`api/openfuyao_schemas.py` | `/openfuyao/clusters*`、`/openfuyao/apps*` |
| CLI | `openfuyao_cli.py` | `cluster preflight/create/status/list/destroy/logs`、`app install/status/list`；`--json` 信封 + 退出码契约 |
| 测试 | `tests/unit/test_openfuyao_cluster_*.py`、`test_openfuyao_app_service.py` | 校验/渲染/映射/幂等/负例，共 30 条 |

**实测关键结论**（补充 §11.1）：

- 预检 `results[].status` 是**大写** `PASS/FAIL`，映射必须大小写无关；
- `BKECluster.status.ready=true` 比 condition 更稳（`ClusterReady/Healthy/Ready` 阶段
  condition 里还有 `Addon=False`，但 `ready` 已为 true）；
- `bke cluster create` 会**阻塞到 addon 部署完成**（本次约 10 分钟）后才退出，
  所以“退出码非 0 也继续轮询 CR”的策略仍保留，但正常路径不会提前退出；
- 业务节点名严格等于 `spec.hostname`（worker 的 OS hostname `localhost.localdomain`
  不参与），L4 用 `kubectl get nodes` 的 `hostname` 对齐。

**未交付**：面板节点表（§11.6）、建好后扩容（依赖未注册的 `bke cluster scale`）、
远端节点自动清理（禁止 `bke reset`）。
