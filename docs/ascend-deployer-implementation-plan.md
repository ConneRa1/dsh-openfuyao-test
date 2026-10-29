# Ascend Deployer 集成决策与实施方案

> 版本：v2.0 · 2026-10-29
> 状态：待 G0 实机验证后进入开发
> 本文替代 `ascend-deployer-architecture-review.md` 作为后续实施依据；此前文档继续作为场景与概念参考。
> 注意：当前仓库没有 Ascend Deployer 的 Python 实现、CLI 或 preset agent。本文中的 `witty-service ascend ...` 全部是**待实现契约**，不是现有命令。

---

## 0. 执行摘要

### 0.1 是否还有必要集成

**有必要，但只应作为 standalone 昇腾节点的补位能力集成；没有必要把它接入 openFuyao 的标准部署主链路。**

它不可替代的价值是：

- 不进入 Kubernetes / openFuyao 的物理机，批量或离线安装驱动、固件、CANN 和工具链；
- openFuyao 尚未覆盖、但 Ascend Deployer 官方明确支持的硬件与版本组合；
- 后续确有需求时，为未被其他控制器接管的既有 K8s 安装特定 MindCluster 组合。该场景必须单独立项验证，不属于首个版本。

它不能解决当前 openFuyao 环境中的这些问题：

- 没有 NPU 卡；
- BKE / Kubernetes 版本不满足 InferNex 要求；
- 容器镜像缺 CANN、框架或推理引擎；
- InferNex、模型服务和上层应用部署。

因此，如果近期产品只有 openFuyao 集群交付，没有 standalone 节点交付需求，**应暂缓写入能力，优先补齐 openFuyao 的版本矩阵、真实硬件和应用链路**。

### 0.2 对现有裁剪方案的最终判断

保留：

- 独立 `ascend-deployer` agent；
- Agent 只调用后端 CLI，不直接执行 `install.sh`；
- 早期不加 REST API、数据库表、Web 面板；
- 默认节点池分流，不承诺同机接力；
- 从单一、明确、经过验证的 profile 开始。

必须修正：

1. **恢复最小状态机和任务锁。** 文件锁不是状态机的替代品，Ansible retry 也不等于安全续跑。
2. **所有权必须采用“声明记录 + 动态探测”双保险。** 只探测无法覆盖“已规划但未安装”“无卡导致 Operator 空转”和检查后的竞态。
3. **首个写入版本前台执行。** 现有 `CommandRunner` 会等待子进程，不支持 CLI 退出后可靠更新状态；不能直接采用“后台启动并立即返回 ID”的设计。
4. **平台任务记录与厂商产物分权。** `status.json` 是平台控制记录，Ascend JSON 是执行证据，实际探测是验收证据；任何一份文件都不是“永远权威”。
5. **不默认自动回滚、自动重启、自动续跑。** 驱动/固件变更和中断恢复需要显式人工确认。
6. **将 `report` 与 `verify` 分开。** 查询报告不能隐式执行 `--test=all`。
7. **从第一版加入计划摘要、包校验、凭据保护和共享所有权门禁。** 这些不是规模化阶段才有的附加项。

### 0.3 推荐交付策略

```text
G0 真实工具验证与 Go/No-Go
  → P0 只读预检 + 兼容门禁 + 所有权
  → P1 单台 standalone 物理机、前台安装、人工重启、显式续跑与验证
  → P2 小批量/离线、canary、可靠 worker、部分失败处理
  → 另行立项：特殊 K8s / MindCluster 组合

不进入默认路线：同机接力、自由升降级、自动固件回滚、开放任意组件组合
```

---

## 1. 评估依据与事实边界

### 1.1 输入资料

- `ascend-vs-openfuyao-scenarios.html`：节点池分流、组件 owner、使用场景；
- `ascend-stack-concepts-and-flow.html`：软件栈分层、NPU Operator 与 Ascend Deployer 的平行关系；
- `ascend-deployer-integration.html`：原始集成方案、风险与验收项；
- `ascend-deployer-architecture-review.md`：薄 CLI、无 DB 的裁剪方案；
- 《部署类 Skill 通用方法设计》：形态判定、环境检查、兼容矩阵、幂等执行、验证和回滚方法。

### 1.2 已由当前代码证实的事实

- `witty-service` 入口是 `src/witty_service/cli.py`；openFuyao `preflight` 直接调用 application 层，但 `deploy/status/logs` 走本机 REST。
- `application/openfuyao/process.py` 的 `CommandRunner` 会等待进程并通过 PIPE 读取输出；`start_new_session=True` 只用于进程组管理，不是持久 worker。
- openFuyao 的后台部署依赖常驻服务中的 `asyncio.create_task`；服务关闭会取消任务，重启后将任务标记为中断，不会自动续跑。
- `log_tail.py` 可复用；`process.py` 的进程组执行/回收可复用，但其异常与 openFuyao 错误码有耦合。
- `sudo -n` 只是非交互提权方式，不等于已经配置 sudoers 白名单。
- 默认工作区是调用者的 `~/.witty`；CLI、服务和 sudo 后身份不同，可能解析到不同 HOME。
- 当前没有 Ascend preset agent；现有 agent 的 skill 仓库通过 `skill_source` 装载。仓库中没有 Ascend 实现。

### 1.3 仍需实机验证的外部假设

以下事项不能仅靠文档进入生产代码：

- 各目标版本 `install.sh` 的真实参数、退出码和 EULA 行为；
- `--check` 是否只改变控制机文件、是否完全不改变目标机配置；
- `deployer_progress_output.json`、`check_res_output.json`、`report.json` 的路径、 schema、覆盖规则和失败时的完整性；
- 已安装组件是否可靠跳过，重跑是否可能升级、降级或改写配置；
- Ansible retry 能否覆盖整个安装阶段，而不是只记录失败主机；
- 哪些组件会安装或重启 Docker/containerd/kubelet；
- 驱动/CANN 安装后如何可靠判断需要重启；
- `--test` 各模式的覆盖范围、副作用和“未安装”的语义。

这些项目全部纳入 G0，不在代码中先写成既定事实。

---

## 2. 集成价值与边界

| 需求 | 是否集成 Ascend Deployer | 原因 |
|---|---:|---|
| standalone 物理机首次安装驱动/固件/CANN | **是，核心价值** | openFuyao / NPU Operator 不覆盖非集群节点 |
| 离线、小批量、统一版本的独立节点交付 | **是，核心价值** | 符合 inventory + 离线包 + 一次性执行模型 |
| openFuyao 未覆盖但厂商已验证的新机型 | **条件是** | 必须有官方支持矩阵和真实测试环境，不能仅因“新”就放行 |
| 标准 openFuyao 集群驱动/Device Plugin | 否 | NPU Operator 已是声明式标准路径 |
| 容器内 CANN、PyTorch、MindSpore、推理引擎 | 否 | 应由镜像解决，不应污染宿主机 |
| InferNex、模型服务、普通应用 | 否 | 属于 K8s 负载和应用层 |
| 已有 K8s 上补特殊 MindCluster 组合 | 后续单独立项 | 价值存在，但 owner、CRD、DaemonSet 和版本冲突风险高 |
| Ascend 先装、再同机交给 BKE/NPU Operator | 默认不做 | 不是简单接力，而是所有权迁移和环境清理工程 |
| 无卡环境下“让 NPU Operator 有事做” | 不做 | 无卡是明确等待状态，引入第二套工具只会制造冲突 |

### Go 条件

同时满足以下条件才进入 P1 写入能力：

1. 有明确的 standalone 节点交付需求；
2. 有一台可重装、可人工重启、带真实 NPU 的验证机，执行机与目标机分离；
3. 至少一个“Deployer 版本 + 硬件 + OS + 内核 + 架构 + 驱动/固件/CANN”组合得到官方支持并完成 G0；
4. 离线包来源、许可证和 SHA256 可追溯；
5. 能可靠判定阶段成功、节点成功和需要重启，或能够将不确定结果显式标记为 `unknown`；
6. EULA 能以用户显式同意为前提被可靠处理；不能处理时，首版去掉相关组件，而不是模拟无限输入 `y`。

任一条件不满足，只保留文档/人工 runbook 或 P0 只读能力，不承诺自动铺装。

---

## 3. 对通用 Skill 方法的裁剪

通用方法的“五阶段闭环”保留，但原则需要按驱动/固件的现实调整：

| 通用原则 | 本方案的落地方式 |
|---|---|
| 形态三连判 | 首版只接受“底层宿主机软件 + 单机物理机 + standalone”；集群、容器、虚机、应用全部拒绝 |
| 环境检查 | 执行机、目标机、包、权限、owner、维护窗口分别检查；失败即停止 |
| 兼容性查表 | 使用不可变 YAML profile 白名单；未命中即拒绝，不做“最接近版本”推断 |
| 幂等执行 | 完全相同且已验证返回 `already_satisfied`；已有不同版本按“变更场景”拒绝，不自动升降级 |
| 不验不算完成 | 进程退出成功不等于部署成功；必须核对版本、NPU 可见性和 profile 声明的最小用例 |
| 失败自动回滚 | **不采用**。首版采用停止后续阶段、保留证据、给出恢复建议；只有逐组件验证过的回滚才可另开能力 |
| 集群通信验证 | P2 才加入；多机 HCCL/RoCE 不属于单机验收 |

特别说明：**验证失败也不能盲目自动回滚。** 此时系统可能处于驱动已替换、内核模块未加载或固件已写入的中间态，自动执行旧包可能进一步扩大破坏面。

---

## 4. 目标架构

```text
用户
  │
  ▼
ascend-deployer Agent
  │  只负责：形态路由、参数收集、影响面说明、确认、结果解释
  ▼
两个 Skill：ascend-node-preflight / ascend-stack-deploy
  │  只负责：流程和拒绝规则；不保存另一份安装脚本或版本矩阵
  ▼
witty-service ascend ... --json
  │  CLI 直接调用 application；早期无 REST、无 DB
  ▼
application/ascend
  ├─ profile：不可变 profile 与兼容白名单
  ├─ preflight：执行机/目标机/owner/包/权限门禁
  ├─ service：计划摘要、最小状态机、显式续跑、阶段编排
  ├─ state：原子状态、事件、任务锁、证据快照
  ├─ runner：前台执行；P2 才增加独立 worker
  └─ report_parser：按 Deployer 版本适配 JSON，失败时返回 unknown
  │
  ├──────────────► 共享 node_ownership（Ascend 与 openFuyao 都检查）
  ▼
固定绝对路径中的 Ascend Deployer + 只读离线包
  ▼
目标 standalone 物理机
```

### 4.1 三类信息不能混为一谈

| 信息 | 权威来源 | 用途 |
|---|---|---|
| 用户要做什么 | 不可变 plan | 目标节点、profile、包摘要、维护窗口、EULA、确认摘要 |
| 平台执行到哪一步 | deployment 控制记录 + event log | 状态机、审计、中断判定 |
| 厂商工具报告了什么 | 每次执行后复制的 JSON 证据快照 | 解析节点结果和版本，不直接覆盖平台状态 |
| 机器现在实际是什么状态 | 实时探测 + 独立 verify | 最终验收和漂移判断 |

缺失、损坏、过期或 schema 未知的厂商 JSON 只能导致 `unknown` 或 `verification_failed`，不能推导出成功。

### 4.2 最小状态机

```text
planned
  → prechecking → ready
  → installing
  → awaiting_reboot ──人工重启 + 显式 resume──→ installing
  → verifying
  → succeeded

任意执行阶段 → failed
进程消失且没有正常终态 → interrupted
P2 批量：部分节点验收成功、部分失败 → partially_succeeded
```

规则：

- `awaiting_reboot` 是正常等待状态，不是错误，也不是终态；
- `interrupted` 必须带 `recovery_required=true`，禁止服务启动时自动重跑；
- `resume` 只允许使用相同 plan、相同包摘要、相同 Deployer 根目录，并在重新预检后执行；
- 首版没有“任意时刻安全取消”的承诺。超时或进程被杀后统一进入 `interrupted`，不谎报已回滚；
- 状态迁移集中由 `service.py` 完成，CLI 和 parser 不得各自拼状态。

### 4.3 所有权：声明记录与探测缺一不可

动态探测只能回答“现在看到了什么”，无法回答：

- 节点已经分配给 openFuyao，但尚未开始安装；
- NPU Operator 已安装，但因无卡尚未产生 DaemonSet；
- 预检通过后、真正写入前，另一个 agent 已经开始变更；
- 查询用了错误的 kubeconfig，或当前账号无权看到业务集群。

因此需要一个小型、文件-backed 的共享 claim store，而不是新增三张数据库表：

```json
{
  "schema_version": 1,
  "node_id": "<machine-id 或已验证的稳定身份>",
  "pool": "standalone",
  "owner": "ascend-deployer",
  "claim_id": "<uuid>",
  "claimed_at": "<RFC3339>",
  "source_plan": "<plan-id>"
}
```

约束：

- Ascend 和 openFuyao 在任何写入前都必须经过同一 claim/check 路径；
- 写入前同时持有节点锁，重新检查 claim 和实时状态，消除检查—执行竞态；
- 探测到已有其他 owner 时，即使本地没有记录也拒绝；
- 声明为 openFuyao 但无法完成探测时 fail closed，不按“无痕迹”放行；
- 尚未发生任何目标机变更的失败任务可释放 claim；一旦开始写入，claim 保留，直到清理/重装后显式释放；
- 首版不提供 `force-ownership-transfer`，跨池迁移不通过改一个字段完成。

---

## 5. 不可变计划与 CLI 契约

### 5.1 Plan 是确认边界

`preflight` 成功后生成不可变 plan。`plan_digest` 至少覆盖：

- 规范化目标节点清单与稳定节点身份；
- profile 完整内容和 Deployer 版本；
- 组件列表、资源 manifest 和每个包的 SHA256；
- 维护窗口（含时区）；
- EULA 文本或许可证 manifest 摘要；
- 执行机、Deployer 根目录和报告目录约定；
- preflight 结果摘要。

密码、私钥内容、敏感命令行和完整原始 inventory 不进入 plan 或日志。

`deploy` 必须满足：

1. `--confirm` 中的摘要与 plan 完全一致；
2. 当前时间处于维护窗口；每个变更阶段开始前再次检查，不在软件包事务中硬停；
3. 节点锁和 claim 获取成功；
4. 重新检查 owner、包摘要和关键目标状态；
5. 涉及许可证时，`--accept-eula` 的摘要与 plan 一致，并记录操作者、时间和组件范围；
6. 任一项变化则要求重新 preflight，不能沿用旧确认。

### 5.2 首版命令

```bash
# 只读目标探测 + 兼容判定；在控制面保存 preflight/plan
witty-service ascend preflight \
  --inventory <path> --profile <name> \
  --maintenance-window <RFC3339-start>/<RFC3339-end> --json

# P1：前台执行，完成当前阶段后才返回；不会“启动后立即返回 ID”
witty-service ascend deploy \
  --plan <plan-id> --confirm <plan-digest> \
  --accept-eula <license-digest> --actor <user-id> --json

# 人工重启后，重新预检并继续同一个计划
witty-service ascend resume \
  --deployment <id> --confirm <plan-digest> --actor <user-id> --json

# 查询控制记录；P2 worker 模式下才增加 --wait
witty-service ascend status --deployment <id> --json

# 读取日志游标
witty-service ascend logs --deployment <id> --cursor <n> --json

# 主动执行只读/最小冒烟验证
witty-service ascend verify --deployment <id> --json

# 只解析已保存证据，不触发 --test 或任何安装动作
witty-service ascend report --deployment <id> --json

# 查看共享所有权记录
witty-service ascend ownership list --json
```

不涉及许可证的 profile 不需要 `--accept-eula`。首版的 `deploy/resume` 都是前台命令；Agent 必须等待命令结果，不能用 shell 的 `&` 自行转后台。

### 5.3 输出与退出码

所有 `--json` 命令只输出一个 JSON 文档，包含 `schema_version`、`ok`、`data`、`error`；日志写任务文件，不与 JSON 混在 stdout。

退出码只表达本次命令是否成功完成，不将正常业务状态伪装成异常：

| 退出码 | 含义 |
|---:|---|
| 0 | 命令成功返回有效结果；包括 `status=awaiting_reboot` 和 `already_satisfied` |
| 1 | 安装、续跑或验证失败 |
| 2 | 参数、plan 摘要或确认信息错误 |
| 3 | 预检、兼容性、owner、维护窗口等安全门禁拒绝 |
| 4 | 内部错误或无法判定的中断 |

**不新增“5=需要重启”。** `status --json` 能正常返回 `awaiting_reboot` 时退出码应为 0，下一步由 `next_action` 表达。

---

## 6. 状态目录、执行模型与安全

### 6.1 路径和身份

新增统一的 `WITTY_DEPLOYMENT_STATE_ROOT`，生产环境必须是绝对路径，例如 `/var/lib/witty-service/deployment`；开发默认值才可基于 `WorkspaceSettings.root_path()`。禁止依赖 sudo 后的 `$HOME` 猜报告位置。

```text
<state-root>/
  ownership/
    nodes.json
    lock
  ascend/
    plans/<plan-id>.json
    deployments/<deployment-id>/
      status.json
      events.jsonl
      logs/
      artifacts/
    locks/
      executor.lock
      nodes/
```

- plan 创建后只读；status 使用临时文件 + `fsync` + 原子替换；
- event log 记录操作者、阶段、命令摘要、退出码和证据 hash，不记录秘密；
- 状态目录默认 0700，敏感文件 0600；日志必须有大小和保留上限；
- 厂商 JSON 每次阶段结束复制到独立 `artifacts/<stage>/`，保存 hash 和采集时间，避免下一次运行覆盖历史；
- 如果厂商工具只能写全局固定目录，P1 同时只允许一个部署，并在每个阶段立即快照；P2 再决定是否引入独立 workdir。

### 6.2 P1 前台执行

复用 `CommandRunner` 的等待、超时和进程组回收语义：

- CLI 进程在整个变更阶段存活；
- stdout/stderr 持续写任务日志；
- 超时、调用取消或服务关闭时杀进程组，并将任务标为 `interrupted`；
- 不把 `start_new_session` 当作后台持久化；
- 不用 `setsid ... &`、裸 `Popen` 或 Agent shell `&` 绕开状态管理。

这会牺牲首版的“立即返回”，但能保证状态和执行事实一致。只有真实批量需求出现后，才在 P2 实现独立 worker。

### 6.3 P2 worker 的最低要求

P2 若增加后台模式，worker 必须：

- 是独立、可识别的固定命令，输出重定向到文件而非 PIPE；
- 保存 PID、进程启动时间和 deployment_id，防止 PID 复用误判；
- 正常结束时写入终态；`status` 或启动恢复发现进程消失且无终态时标记 `interrupted`；
- 服务/容器重启后不自动续跑；
- worker 是否存活不能单独作为节点安装成功的依据；
- 与目标节点锁、执行机锁和 claim 使用同一套状态存储。

不满足这些条件时，P2 仍保持前台执行，不交付伪后台能力。

### 6.4 凭据、SSH 与提权

- 首版只支持密钥或既有的安全凭据引用，不支持把 `ansible_ssh_pass` 写进 plan、日志或对话；
- 私钥只通过受控路径/agent 引用，权限和属主纳入 preflight；
- 禁止 `StrictHostKeyChecking=no` 和未确认的 `ssh-keyscan` 自动信任；使用预置 known_hosts 或显式 TOFU 记录；
- 安装命令使用固定 argv，不使用 `shell=True`；组件、路径和 profile 全部来自白名单；
- sudoers 只允许 root 所有的固定绝对路径及必要参数，不开放通用 `sudo bash`；
- 记录 argv 前进行脱敏；EULA 输入、密码和私钥内容不得出现在日志；
- 执行机首版不能同时是目标机，避免重启或进程回收把控制面一起中断。

### 6.5 EULA 与离线包

EULA：

- 优先使用厂商正式支持的非交互参数/配置；
- 没有正式接口时，只允许精确匹配已知提示和版本的受控交互，未知提示立即超时失败；
- 不允许 `yes | install.sh` 或对任意提示自动输入 `y`；
- Agent 不得替用户默认接受，用户确认必须绑定许可证摘要。

离线包：

- 从 P1 就有 `manifest`：文件名、组件、版本、大小、SHA256、来源、许可证摘要；
- Deployer 根目录和 resources 在 plan 生成后不得变化；deploy 前重新计算摘要；
- 同组件多版本混放、缺包、未知包或 hash 不匹配一律拒绝；
- 不在部署阶段隐式联网下载“缺失依赖”。

---

## 7. Profile、验证与恢复策略

### 7.1 首版只做白名单 profile

不做通用版本求解器。每个 YAML profile 对应一个经过验证的完整组合：

```yaml
schema_version: 1
name: standalone-a2-example
deployer_version: "<G0 确认>"
hardware_model: "<G0 确认>"
npu_model: "<G0 确认>"
os_release: "<G0 确认>"
kernel_constraint: "<G0 确认>"
arch: "<G0 确认>"
components:
  npu: {driver: "<version>", firmware: "<version>"}
  toolkit: {version: "<version>"}
  kernels: {version: "<version>"}
resource_manifest: "<path>"
eula_digest: "<digest-or-null>"
verification_suite: single_npu_smoke
source:
  official_document: "<url>"
  validated_on: "<date>"
```

`a2-910b` 只能作为展示名，不能代替完整版本组合。检测到未知硬件、OS、内核、架构或已有不同版本时直接拒绝。

### 7.2 验证分层

| 层级 | 验证内容 | 不能替代它的证据 |
|---|---|---|
| 进程层 | 命令退出码、阶段是否完整执行 | 不能证明所有节点成功 |
| 报告层 | 节点级安装结果、包版本、失败项 | 不能证明重启后驱动实际可用 |
| 系统层 | `npu-smi`、设备数量、驱动/固件/CANN 实际版本 | 不能证明业务框架可用 |
| 冒烟层 | profile 指定的单卡初始化或最小程序 | 不等于多机 HCCL、推理或训练验收 |

P1 只承诺单机和单卡/单机规定冒烟。P2 才增加节点间检查；HCCL/RoCE、容器注入、推理和训练属于各自专项验收，不能由 `--test=all` 一笔带过。

### 7.3 恢复，而不是虚假回滚承诺

首版失败策略：

1. 停止尚未开始的阶段，保留当前节点 claim；
2. 保存日志、厂商产物和实际版本快照；
3. 将节点标为 `failed` 或 `unknown`，任务不得自动显示成功；
4. 给出官方支持的清理、重装、旧版本恢复或继续安装建议；
5. 只有相同 plan 且重新预检通过时才允许 `resume`；
6. 已装不同版本、降级、固件回退、跨池迁移全部拒绝并转人工。

后续若增加回滚，必须逐组件提供“支持矩阵 + 快照 + 实机测试 + 回滚后验证”；不能用通用 `rollback.py` 包装一个卸载命令就宣称安全。

---

## 8. 代码与交付物地图

### 8.1 witty-service

新增：

| 文件 | 责任 |
|---|---|
| `src/witty_service/ascend_cli.py` | argparse、单文档 JSON、退出码，不写业务状态 |
| `src/witty_service/domain/ascend.py` | 状态、阶段、错误码和结果模型 |
| `src/witty_service/application/ascend/profile.py` | YAML 白名单加载、严格校验、资源 manifest |
| `src/witty_service/application/ascend/preflight.py` | 执行机/目标机探测和门禁 |
| `src/witty_service/application/ascend/service.py` | plan、最小状态机、deploy/resume/verify 编排 |
| `src/witty_service/application/ascend/state.py` | 原子状态、事件、任务锁、证据快照 |
| `src/witty_service/application/ascend/runner.py` | 固定 argv、前台执行、日志、超时与中断 |
| `src/witty_service/application/ascend/report_parser.py` | 按版本适配、证据校验、unknown 语义 |
| `src/witty_service/application/node_ownership.py` | Ascend/openFuyao 共享 claim 与节点锁 |
| `src/witty_service/data/ascend_profiles/<name>.yaml` | 首个经过 G0 的完整组合 |
| `src/witty_service/data/preset_agents/ascend-deployer/agent.yaml` | 独立入口和硬安全边界 |

修改：

- `src/witty_service/cli.py`：挂载 `ascend` 子命令；
- `src/witty_service/config.py`：统一部署状态根目录和 Ascend 绝对路径配置；
- openFuyao 写入前的 preflight/service：接入同一个 ownership 检查，避免只约束 Ascend 一侧。

复用但不照搬：

- `application/openfuyao/log_tail.py`：直接复用日志游标；
- `application/openfuyao/process.py`：复用等待/取消/进程组能力，Ascend 自己的错误模型在 `runner.py` 适配；
- `domain/openfuyao.py::ExitCode`：只参考数值约定，不复用 Environment 状态判断。

P2 才新增独立 `worker.py`；没有 P2 后台需求则不创建。

### 8.2 Agent 与 Skills

两个 skill 保留不同风险边界：

- `ascend-node-preflight`：形态三连判、信息收集、只读预检、owner/版本解释；
- `ascend-stack-deploy`：影响面确认、plan digest、deploy/resume/verify/report、恢复建议。

Skill 中不再复制一套 `install.py/preflight.py/rollback.py`，确定性逻辑只在 application 层。版本事实只由 profile YAML 提供，避免 Skill 文档和后端各维护一份矩阵。

Agent 硬规则：

- openFuyao、容器内软件、应用或推理需求立即路由到对应工具，不尝试 Ascend 补装；
- 不直接运行 `install.sh`、`reboot`、`sudo`、`kubectl` 或 `helm` 改变目标；
- 不绕过 preflight，不自行缩短维护窗口，不替用户接受 EULA；
- 确认必须引用 plan 摘要；摘要变化必须重新确认；
- `interrupted` 不自动 resume，报告缺失不宣布成功；
- 输出固定为“现状 → 计划/影响面 → 执行 → 验证 → 恢复建议”，没有已验证回滚时明确写“无自动回滚”。

生产发布时 skill 来源必须固定到不可变版本，不能直接跟随可移动的 `master`。

### 8.3 运维交付物

代码完成不等于可交付，还必须提供：

- 首个 profile 的官方来源、验证记录和包 manifest；
- sudoers/known_hosts/目录权限配置样例；
- 人工重启、interrupted 恢复、claim 释放和节点重装 runbook；
- 日志保留、任务清理和敏感信息检查规则；
- 明确的支持/拒绝矩阵，防止 Agent 对未验证环境做承诺。

---

## 9. 分阶段实施与门禁

### G0：真实工具验证与 Go/No-Go

**不写自动部署代码。** 在可重装的单台真实 NPU 目标机上，使用独立执行机验证一个精确组合。

必须产出：

1. 实际命令、退出码、交互、目标机副作用清单；
2. 三种 JSON 的真实样本：成功、失败、部分失败、缺失/损坏；
3. 重跑、已装不同版本、进程中断、人工重启后的行为；
4. 哪些包触发 Docker/containerd/kubelet 变化；
5. EULA 的可靠非交互方式及许可证摘要来源；
6. 驱动/CANN 的实际验证命令和“需要重启”的判定依据；
7. 包 manifest、官方支持链接和可恢复验证环境。

**Go：** 能安全判定、能复现、能恢复，且 standalone 需求真实存在。
**No-Go：** 依赖猜日志、无法判定部分成功、EULA 只能暴力应答、没有可恢复测试机或没有实际场景。No-Go 时停止集成，不进入 P0/P1 写能力。

### P0：只读接入

实现：

- profile 白名单、manifest 校验；
- 形态路由、执行机/目标机/owner/版本 preflight；
- 共享 ownership 检查，openFuyao 写入路径同步接入；
- plan 与 digest；
- `preflight/report/ownership list` 所需的最小解析与状态存储；
- 独立 agent 模板和 preflight skill。

验收：

- 无卡、未知 OS/硬件/内核、未知 profile、缺包/hash 错误均拒绝；
- openFuyao 已声明或可探测接管的节点均拒绝；
- 无卡但已有 openFuyao claim 的节点不能被误判为空闲；
- 并发 preflight/deploy 模拟不会绕过 claim；
- 日志、JSON、plan 中无私钥、密码和 EULA 输入；
- 不改变目标机配置。

### P1：单台 standalone 写入闭环

实现：

- 前台 `deploy`、最小状态机、执行机锁和节点锁；
- 阶段执行、日志、证据快照、`status/logs/report`；
- `awaiting_reboot` 后由用户人工重启，`resume` 重新预检；
- `verify`、already-satisfied 幂等和 interrupted 语义；
- deploy skill 和完整 Agent 工作流。

首个写入范围：

- 一个 profile；
- 一台 standalone 物理机；
- 首次安装，不做升降级；
- 先完成驱动/固件，再加入 G0 已验证的 CANN/toolbox；
- 无自动重启、自动回滚、强制取消和跨池迁移。

验收：

- 安装、人工重启、续跑、验证全链路通过，实际版本与 profile 一致；
- 相同状态重跑不调用变更命令，返回 `already_satisfied`；
- plan、包、inventory、窗口、EULA 任一变化均无法复用旧确认；
- 超时/杀进程/服务重启后任务为 `interrupted`，不会自动重跑或伪报成功；
- JSON 缺失、陈旧、损坏、schema 变化时不崩溃、不谎报；
- openFuyao 节点和已有不同版本的节点 100% 被拒绝；
- 没有敏感信息进入日志、事件、JSON 和 Agent 输出。

P1 未全部通过，不进入批量。

### P2：小批量与离线交付

实现：

- canary 一台，明确通过后才允许其余节点；
- 默认串行变更；并发只有在厂商 workdir 和产物隔离验证后开放；
- 节点级结果、部分失败、仅失败节点显式重试；
- 如确有后台需求，按 §6.3 实现 worker；否则保持前台；
- 批量人工重启后的恢复和逐节点 verify；
- 自动 reboot 只有在独立执行机、逐节点确认和真实故障测试全部通过后才能单独启用。

验收：

- 一台失败不影响定位，未开始节点不继续变更；
- 好节点与坏节点分别报告，不把批任务压成一个布尔值；
- 重复/并发请求不能重复安装同一节点；
- worker 或服务重启不会造成重复执行；
- 断网环境不隐式下载，包缺失在写入前失败；
- canary 未通过时其余节点零变更。

### 后续单独立项：特殊 K8s / MindCluster

只有出现真实需求才启动，必须重新完成：

- 每类组件 owner 映射；
- 业务集群 kubeconfig 和节点级接管探测；
- CRD/DaemonSet/Helm release 冲突测试；
- Deployer、OS、K8s、volcano-ext 等精确矩阵；
- 清理、转移、升级和回退路径。

它不能由 P2 自动“平滑升级”得到，也不再预设 P3 一定实施。

---

## 10. 测试设计

### 10.1 无 NPU 即可完成的测试

使用 fake `install.sh` 和真实 JSON 样本，不模拟业务成功，只验证平台行为：

- profile/manifest/plan digest、路径穿越和组件白名单；
- owner claim、节点锁、并发和检查—执行竞态；
- 原子状态、事件、日志游标、证据覆盖防护；
- EULA 已知/未知提示、超时和确认摘要；
- 进程退出非零、hang、timeout、kill、PID 复用和 worker 中断；
- JSON 成功/失败/部分失败/空文件/旧任务/未知 schema；
- 凭据和 argv 脱敏；
- CLI 单文档 JSON 与退出码；
- openFuyao 和 Ascend 两侧互相拒绝。

可仿照现有 `test_openfuyao_process.py`、`test_openfuyao_log_tail.py`、`test_openfuyao_cli.py` 的隔离方式，但不要为复用而引入 openFuyao 的 Environment 状态机。

### 10.2 真实 NPU 验收

至少覆盖：

1. 干净 standalone 节点成功；
2. 无卡、未知硬件、未知 OS 和 openFuyao 节点拒绝；
3. 同 plan 重跑无变更；
4. 已有不同版本拒绝；
5. 安装中中断后的状态和恢复；
6. 人工重启后驱动与最小用例可用；
7. 报告缺失时不宣布成功；
8. P2 canary 失败时其他节点不变；
9. 全链路敏感信息扫描；
10. 验证机可按规定流程恢复或重装。

### 10.3 发布 Definition of Done

- 所有支持项都有 profile、manifest、自动测试和实机记录；
- 所有拒绝项都有结构化原因，Agent 不绕过；
- 任一失败都能定位到 deployment、阶段、节点和证据；
- 任一中断都不会自动重放破坏性操作；
- 任一成功都有独立 verify，而不是只看脚本退出码；
- 没有虚假的后台、取消、回滚、跨池或兼容承诺；
- 运维 runbook 可执行，支持边界与 Agent 行为一致。

---

## 11. 明确不做与最终决策

首版明确不做：

- REST API、数据库 migration、独立 Web 面板；
- 后台立即返回、自动服务恢复、任意时刻安全取消；
- 自动重启、自动固件/驱动回滚；
- 已有版本自由升级/降级；
- openFuyao 同机接力或强制 ownership transfer；
- MindCluster 调度组件、K8s 安装、MindIE/InferNex/应用编排；
- 通用任意版本组合求解；
- 密码明文 inventory 和不受控 SSH host key 信任。

**最终建议：保留集成方向，但将项目定义为“standalone 昇腾节点受控铺装”，而不是“Ascend Deployer 全能力平台化”。先用 G0 证明一个真实组合，再完成 P0/P1；P2 以批量安全为边界，特殊 K8s 场景另立项目。**

如果 G0 不通过，或没有 standalone 交付需求，停止集成是合理结果，不代表项目失败；继续堆叠后端文件反而会增加一个无人能验收的高风险入口。
