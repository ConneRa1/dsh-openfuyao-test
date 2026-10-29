# Ascend Deployer 集成架构评估与裁剪方案

> 版本：v1.0 · 2026-10-28
> 依据：[ascend-deployer-integration.html](ascend-deployer-integration.html) + 项目现有 openFuyao 实现

---

## 一、评估结论

原报告的整体方向**正确**：独立 agent 入口、CLI 契约、节点池分流、预检拒绝逻辑，这些判断都对。但方案存在**明显的过度设计**——为一个「一次性 Ansible 任务执行器」配了一整套「长期运行平台」才有的基础设施。

原报告方案新增约 15 个文件（含 DB migration、ORM、REST schemas），本质上是在为一个 shell 脚本包装器建一套微型平台。

## 二、过度设计在哪

对照 openFuyao 的实际架构，原方案多出了三层不必要的东西：

| 组件 | openFuyao 为什么需要 | Ascend Deployer 是否需要 |
|------|---------------------|------------------------|
| **REST API 层** | 有持久状态（环境/集群/应用生命周期）、多入口（CLI + 前端面板 + Agent）、长期运行服务（console 健康检查、observe 感知） | **不需要**。Ascend Deployer 是「跑完即走」的任务型工具，只有 Agent 一个入口，没有长期状态需要对外暴露 |
| **3 张数据库表** | 环境/集群/应用是持久实体，需要 CRUD、审计、关联查询 | **不需要**。Ascend Deployer 的 JSON 产物（`report.json`、`check_res_output.json`、`deployer_progress_output.json`）已经是权威状态来源，DB 是重复存储 |
| **完整状态机 + 任务锁** | BKE 部署是多阶段长事务，服务重启后需要恢复 | **不需要**。Ascend Deployer 自身支持断点续跑（Ansible retry + 已装包跳过），平台层重复实现是浪费 |

## 三、推荐架构：薄 CLI + 文件系统状态

### 核心思路

**CLI 直接调用 application 层，砍掉 REST API 和 DB。** 项目里已有先例——openFuyao 的 `preflight` 就是 CLI 直接执行、不走 REST API。

### 架构图

```
用户 / 前端面板
  │ 选择「昇腾软件栈部署」模板
  ▼
ascend-deployer Agent（opencode + bash）
  │ 只调 witty-service ascend ...（--json + 退出码）
  ▼
ascend_cli.py（薄 CLI，直接调 application 层，无 HTTP 跳转）
  │
  ├── application/ascend/preflight.py      只读预检
  ├── application/ascend/runner.py         执行 install.sh（复用 process.py 进程组）
  ├── application/ascend/report_parser.py  解析 JSON 产物
  └── application/ascend/profile.py        profile 加载与校验
  │
  ▼
执行机：install.sh --check / --install / --test
  │
  ▼
状态来源：~/.ascend_deployer/deploy_info/*.json + report/report.json
        （权威状态在文件系统，不在 DB）
```

### 关键设计决策

#### 1. 保留独立 agent 模板，但砍掉后端服务

原报告选择独立 agent 的理由（时间轴互斥、风险模型不同、入口清晰）成立，保留。但 agent 调用的 CLI **不需要经过 REST API**——和 openFuyao 的 `preflight` 一样，CLI 直接 import application 层执行。

```bash
# openFuyao 已有先例：preflight 不走 API
witty-service openfuyao preflight   →  直接调 application.openfuyao.preflight.run_preflight()

# Ascend Deployer 同理
witty-service ascend preflight      →  直接调 application.ascend.preflight.run_preflight()
witty-service ascend deploy         →  直接调 application.ascend.runner.execute()
```

#### 2. 状态用文件系统，不用 DB

Ascend Deployer 的 JSON 产物就是状态。CLI 每次被调用时实时读取文件推导状态，不需要提前写入 DB：

```
任务目录：~/.witty/ascend/<deployment_id>/
  ├── meta.json           # 任务元信息（profile、inventory、创建时间）
  ├── status.json         # 当前阶段（由 CLI 每次更新）
  ├── lock                # 文件锁（防止并发）
  └── logs/               # 执行日志
```

- **并发控制**：`fcntl.flock()` 文件锁，比 DB 锁更简单
- **任务历史**：任务目录 + report.json 就是历史，不需要 DB 审计表
- **断点续跑**：依赖 Ascend Deployer 自身能力（Ansible retry），平台不重复实现

#### 3. 所有权用动态探测，不用台账表

预检时直接探测目标节点状态：

```
检查节点上是否存在：
  - BKE 安装痕迹（/usr/local/bin/bke、bke cluster list）
  - NPU Operator CRD（kubectl get crd | grep npu）
  - Docker/K8s 残留（which docker、which kubelet）

→ 有 openFuyao 痕迹 → 拒绝，引导走 NPU Operator
→ 无痕迹 → 放行
```

不需要维护一张 `ascend_node_ownership` 表——**预检时探测比台账更可靠**（台账可能过期，探测不会）。

#### 4. 复用现有基础设施

直接复用 openFuyao 已有的模块，不重复造轮子：

| 复用模块 | 用途 |
|---------|------|
| `application/openfuyao/process.py` | 进程组管理、`sudo -n` 白名单执行 |
| `application/openfuyao/log_tail.py` | 日志尾部读取 |
| `domain/openfuyao.py` 的 `ExitCode` | 退出码契约（0-4 一致，新增 5 表示需要重启） |

## 四、新增文件对比

| 原报告方案 | 裁剪方案 |
|-----------|---------|
| `domain/ascend.py` | `domain/ascend.py`（仅枚举，~50 行） |
| `application/ascend/profile.py` | `application/ascend/profile.py` |
| `application/ascend/preflight.py` | `application/ascend/preflight.py` |
| `application/ascend/ownership.py` | ~~删除~~（合并入 preflight） |
| `application/ascend/runner.py` | `application/ascend/runner.py` |
| `application/ascend/report_parser.py` | `application/ascend/report_parser.py` |
| `application/ascend/service.py`（状态机） | ~~删除~~ |
| `persistence/ascend_repository.py` | ~~删除~~ |
| `persistence/orm.py` 新增 3 表 | ~~删除~~ |
| Alembic migration | ~~删除~~ |
| `api/ascend.py` + `api/ascend_schemas.py` | ~~删除~~ |
| `ascend_cli.py` | `ascend_cli.py` |
| `data/preset_agents/ascend-deployer/agent.yaml` | `data/preset_agents/ascend-deployer/agent.yaml` |
| 2 个 skills | 2 个 skills |
| **~15 个新文件** | **~7 个新文件** |

## 五、部署流程设计

```
用户：帮我给这批昇腾机器装驱动和 CANN
  │
  ▼
Agent：收集机型、OS、IP 清单
  │
  ▼
witty-service ascend preflight --inventory hosts.ini --profile a2-910b --json
  │
  ├─ 本机门禁：内存 ≥16GB、磁盘 ≥20GB、工具包存在
  ├─ 逐节点探测：OS/架构/NPU 型号/SSH 可达/现有驱动/K8s 残留
  ├─ 所有权检查：节点上有 BKE/NPU Operator → 拒绝（退出码 3）
  └─ 输出：ready + 逐项 checks
  │
  ▼
Agent：复述影响面（节点清单、包清单、是否需要重启、预计耗时）
  │
  ▼
用户确认
  │
  ▼
witty-service ascend deploy --inventory hosts.ini --profile a2-910b --confirm --json
  │
  ├─ 获取文件锁（~/.witty/ascend/lock）
  ├─ 创建任务目录 ~/.witty/ascend/<id>/
  ├─ 后台执行 install.sh --check → --install=sys_pkg,python,npu → --install=toolkit,kernels,...
  ├─ 每阶段结束更新 status.json
  └─ 返回 deployment_id
  │
  ▼
witty-service ascend status --deployment <id> --wait --json
  │
  ├─ 读取 status.json + deployer_progress_output.json
  ├─ 输出：status、phase、progress、节点级结果
  └─ 驱动装完 → 状态 reboot_required（退出码 5）
  │
  ▼
Agent：提示需要重启，用户确认
  │
  ▼
witty-service ascend reboot --deployment <id> --confirm --json
  │
  ├─ 按顺序重启：worker 先、执行机最后
  ├─ 等待节点恢复（SSH 可达）
  └─ 更新 status.json → verifying
  │
  ▼
witty-service ascend report --deployment <id> --json
  │
  ├─ 解析 report.json：每节点驱动/固件/CANN 版本
  ├─ 执行 install.sh --test=all
  └─ 输出：succeeded / failed（含失败节点清单）
```

## 六、两种方案对比

| 维度 | 原报告方案（完整 B） | 裁剪方案（薄 CLI） |
|------|-------------------|-------------------|
| **新增代码量** | ~15 文件，含 DB migration | ~7 文件，零 DB |
| **架构复杂度** | Agent → CLI → REST API → Service → DB → 执行器 | Agent → CLI → 执行器 |
| **状态可靠性** | DB 为权威，可能与实际漂移 | JSON 产物为权威，永远与实际一致 |
| **并发控制** | DB 行锁 | 文件锁（`fcntl.flock`） |
| **断点续跑** | 平台状态机恢复 | 依赖 Ascend Deployer 自身能力 |
| **服务重启恢复** | 从 DB 恢复任务状态 | 从 status.json + JSON 产物推导 |
| **审计能力** | DB 审计表，支持复杂查询 | 文件系统任务目录，支持按时间浏览 |
| **运维成本** | 需要 DB migration、ORM 维护 | 零额外运维 |
| **与 openFuyao 一致性** | 完全同构 | CLI 契约一致，内部更轻 |

## 七、使用场景

### 裁剪方案适合

- **P0-P2 阶段**（原报告规划的全部早期阶段）：预检、单机/小批量铺装、批量离线
- **只有 Agent 一个消费者**：没有前端面板直接调 Ascend API 的需求
- **任务型操作**：执行完就结束，不需要长期跟踪
- **团队规模小**：不想维护额外的 DB schema 和 migration

### 原报告方案适合（何时需要升级到完整方案）

- **出现第二个消费者**：前端面板需要直接展示 Ascend 部署状态、历史列表
- **需要跨服务查询**：比如「显示所有节点上驱动版本低于 X 的机器」这种跨任务聚合查询
- **需要精细审计**：合规要求记录每次操作的完整审计链（谁在什么时间对哪台机器执行了什么）
- **P3 同机接力阶段**：需要所有权台账做跨池迁移的状态跟踪

## 八、升级路径

裁剪方案 → 完整方案的升级是**增量叠加**，不需要推翻重来：

```
裁剪方案（P0-P2）
  │  Agent → CLI → application 层 → 执行器
  │  状态：文件系统（status.json + JSON 产物）
  ▼
第 1 步：加 REST API 层
  │  新增 api/ascend.py + api/ascend_schemas.py
  │  CLI 改为 HTTP 调用（与 openFuyao 的 deploy/status 一致）
  │  application 层不变，仅包一层 HTTP handler
  ▼
第 2 步：加 DB 持久化
  │  新增 persistence/ascend_repository.py + ORM + migration
  │  把文件系统状态同步到 DB（双写过渡，最终 DB 为权威）
  │  CLI 契约、退出码、JSON 产物解析逻辑完全不变
  ▼
第 3 步：加所有权台账
  │  新增 ascend_node_ownership 表
  │  预检时写台账，支持跨池迁移状态跟踪
  │  仅在 P3 同机接力阶段需要
  ▼
完整方案（P3+）
  Agent → CLI → REST API → Service → DB → 执行器
```

每一步都是纯增量，已有的 CLI 契约、退出码、JSON 产物解析逻辑完全不变。

## 九、总结

原报告的方向判断是对的——独立 agent、CLI 契约、节点池分流，这些都应该保留。但把 openFuyao 的「全栈平台架构」原封不动套在 Ascend Deployer 这个「一次性任务执行器」上，多出了 REST API、3 张 DB 表、完整状态机三层不必要的东西。

**建议 P0-P2 用裁剪方案**（7 个文件、零 DB、CLI 直调），把省下来的精力投入到真正有价值的地方——预检规则的完备性、报告解析的容错性、EULA 非交互处理。等 P3 出现前端面板直连需求时，再叠加 REST API 和 DB，届时是平滑升级而非重构。
