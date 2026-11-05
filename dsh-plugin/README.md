# DSH openFuyao 部署插件

这个 bundle 把 openFuyao 的编排 API 投影成 DSH 工具。同一套工具面背后支持两种传输：

| 模式 | 实际运行的东西 | 适用场景 |
| --- | --- | --- |
| `external` | `127.0.0.1:8000` 上已运行的 `witty-service` | 常规开发 / 运维拓扑 |
| `sidecar` | `sidecar/` 里的独立二进制 | 没有跑 `witty-service` 的机器 |
| `auto`（默认） | 外部服务可达就用它，否则起 sidecar | 推荐 |

`auto` **只在外部进程没有监听时**才回退到 sidecar。401/403、缺少 `/openfuyao` API、
或者服务端报错，都会直接报出来，而不是起第二个编排者——两个写者操作同一份数据库会
破坏状态机。

sidecar 用的是原来那套 Python 实现（路由、服务、仓储、状态机、runner）。它由
PyInstaller 打包，所以目标机不需要 Python。sidecar 自己持有一份私有 SQLite 数据库，
位于 DSH 数据目录下的 `plugin-data/openfuyao/`（Host 导出了 `DSH_PROFILE_DIR` 时用
profile 目录，否则用 `~/.dsh`），并绑定到内核分配的 loopback 端口，每次启动生成随机
token。

## 构建 sidecar

必须在目标操作系统与架构上执行（PyInstaller 的产物不能跨架构）：

```bash
uv pip install --python .venv/bin/python 'pyinstaller>=6.10'
./scripts/build-sidecar.sh
rm -rf dsh-plugin/sidecar
cp -a build/sidecar-dist/witty-openfuyao-sidecar dsh-plugin/sidecar
```

产物 `dsh-plugin/sidecar/witty-openfuyao-sidecar` 约 70 MB（onedir；启动更快，且不会在
临时目录里解包）。

## 安装

在仓库根目录把目录作为 profile bundle 安装（profile 的接线由 DSH 插件管理器完成）：

```text
plugin_manager install_bundle target=/root/witty-service/dsh-plugin
```

只装 Host 就够了：右侧边栏面板作为普通依赖随 Host 一起安装，由 Host 的
`cordis.patch.yml` 同时插入 `openfuyao` 和 `openfuyao-panel` 两条 Loader 行。

面板仍然是一个独立的 npm 包，因为 DSH 在启动时会缓存一个包的 `dsh.client` 元数据：
把 Client 半区塞进 Host 包，已经以 Host-only 方式挂载过的 profile 就无法通过热重载
补上面板。

装完先确认工具注册成功，再用：

```text
openfuyao_status
openfuyao_environments
```

本地目录安装会链接这份 checkout。改完插件代码后重载插件（或重启 DSH）；重新构建
sidecar 之后，同样通过重载插件来重启 sidecar。

## 右侧边栏面板

装了 `dsh-better-sidebar` 之后，`panel/` bundle 会通过
`ctx.betterSidebar.registerTab` 注册一个 tab：

- 打开右侧边栏的 **+** 菜单，选 **openFuyao / openFuyao 部署**；
- tab 里显示环境、业务集群、应用的数量、状态与进度，控制台/应用链接，以及 observer
  发现的问题；
- 每个问题都有一个 **询问 DSH** 按钮，它会把一段结构化诊断 prompt 追加到当前会话的
  输入框里（不会自动发送）；
- 没有 ready 环境时，tab 变成预检视图：宿主机预检结果（通过/警告/失败与警告文案），
  带 **重新预检** 和 **确认部署**；
- openFuyao 尚未安装时 Issues 区保持隐藏：既没有 ready 环境、也没有发现集群/应用时，
  observer 返回的条目属于传输噪音，而不是可操作的问题；
- 当已加载的 Host bundle 早于"重新预检"的 POST 路由时，**重新预检** 会退回只读的 plan
  路由，所以版本不一致的安装仍然能刷新检查项，而不是在按钮下面显示 `HTTP 405`；
- **确认部署** 要求显式勾选确认框，然后创建环境记录并启动 Bootstrap；运行期间面板显示
  当前阶段、实时计时器和 `bootstrap.log` 的尾部输出，点 **取消部署** 前会再确认一次；
- **刷新** 重新拉取 overview。应用的安装/回滚/卸载仍然走需要审批的工具。

浏览器永远不直连 sidecar。它调用 Host 路由 `GET /openfuyao/api/overview`，该路由复用
与工具同一个 `Backend` 实例、解析 agent，并返回紧凑的 JSON 快照。因此 sidecar 的端口
与 bearer token 始终留在 Host 侧。

`dsh-better-sidebar` 对 Host 工具是可选的；没有它时 `panel/` bundle 处于非激活状态，
因为它的 Client 半区注入 `betterSidebar`。

## 分发

`./scripts/package-dsh-plugin.sh` 会产出一个自包含归档，用于另一台同操作系统/同架构的
机器。归档结构、安装步骤、传输选择、数据库接管和单写者规则见
[`docs/dsh-openfuyao-distribution.md`](../docs/dsh-openfuyao-distribution.md)。

发 npm 包的版本轴与流水线（含平台分包、发布顺序约束）见
[`dsh-plugin/RELEASING.md`](RELEASING.md)。

## 配置

bundle 会插入这一行：

```yaml
- id: openfuyao
  name: '@openwitty/dsh-openfuyao'
  config:
    mode: auto
    baseUrl: http://127.0.0.1:8000
    agentName: openfuyao-deployer
    requireApproval: true
    panelDeploy: true
```

在 profile 的 `cordis.patch.yml` 里覆盖它：

| 键 | 默认值 | 含义 |
| --- | --- | --- |
| `mode` | `auto` | `auto`、`external` 或 `sidecar` |
| `baseUrl` | `http://127.0.0.1:8000` | 外部 witty-service 地址 |
| `token` | `""` | 外部 bearer token；优先级高于环境变量/文件 |
| `tokenFile` | `/etc/witty-service/witty-service.env` | 从 systemd env 文件读取 `AUTH_TOKEN=` |
| `sidecarPath` | 内置二进制 | 覆盖 sidecar 可执行文件路径 |
| `dataDir` | `$DSH_PROFILE_DIR/plugin-data/openfuyao`，未设置时为 `~/.dsh/plugin-data/openfuyao` | sidecar 的数据库与工作区 |
| `agentName` | `openfuyao-deployer` | external 模式下通过 `GET /agents` 解析 |
| `agentId` | `""` | 跳过按名解析，直接用这个 id |
| `requestTimeoutMs` | `30000` | 普通 HTTP 超时 |
| `deployTimeoutMs` | `1800000` | 预留给长耗时操作 |
| `sidecarStartTimeoutMs` | `45000` | sidecar 就绪等待上限 |
| `requireApproval` | `true` | 变更类模型工具执行前是否询问 |
| `panelDeploy` | `true` | 是否允许面板里用户确认后的 **确认部署** |

外部 token 的读取顺序是 `token` → `AUTH_TOKEN` → `tokenFile`。token 以
`Authorization: Bearer …` 发送，永远不会写进日志。

本 bundle 刻意不导出 schemastery 的 `Config`：本地 `link:` 安装时，Node 按真实路径解析
依赖，checkout 里并没有 DSH 的那些包。默认值在 `lib/config.js`，上表每个键都会被 patch
里的 `config` 整块覆盖。**如果以后要发到 npm**，正确做法是先导出 schemastery `Config`、
再补 `peerDependencies`，两者一起加——只补后者会让每次本地 `link:` 安装时 pnpm 打印
"will not resolve the peer dependencies … might cause issues" 这种误导性警告。

## 工具

只读：

- `openfuyao_status` —— overview（环境、集群、应用、问题、控制台）
- `openfuyao_environments` —— 环境列表/详情字段
- `openfuyao_plan` —— dry-run 宿主机预检
- `openfuyao_logs` —— 环境/集群/应用日志分页
- `openfuyao_health` —— 控制台可达性探测
- `openfuyao_clusters` —— 业务集群列表
- `openfuyao_console` —— 集群的控制台 URL
- `openfuyao_apps` —— 应用列表
- `openfuyao_app_preflight` —— chart/命名空间/端口检查

变更类（受 `requireApproval` 门禁）：

- `openfuyao_prepare` —— 创建/复用环境记录（不 Bootstrap）
- `openfuyao_deploy` —— 启动 Bootstrap
- `openfuyao_app_install`、`openfuyao_app_rollback`、`openfuyao_app_uninstall`
- `openfuyao_cluster_destroy`
- `openfuyao_cancel` —— 停止正在运行的操作（不破坏资源）

集群创建是刻意不提供的：这个分支关闭了 `POST /openfuyao/clusters`，引导用户在 openFuyao
控制台里创建业务集群。插件不会用 `bke`/`kubectl` 绕开 API。

## 安全说明

- sidecar 只监听 `127.0.0.1`、使用内核分配的端口，并要求一个 256 位随机 token，该 token
  通过环境变量传入（不走 argv，`ps` 里看不到）。
- `PR_SET_PDEATHSIG` / 父进程 watchdog 会在 DSH 宿主进程死亡时停掉 sidecar。
- 插件自己的 `tools/pre-execute` 监听器在执行变更类调用前询问。当前 DSH 会话关闭了审批
  能力时，这些调用会被拒绝；只在一次性实验环境里把 `requireApproval` 设为 `false`。
- 面板部署是用户主动发起的动作，因此不走模型工具审批门禁。它需要勾选确认框，并且服务端
  还要 `confirm: true`；把 `panelDeploy` 设为 `false` 可以隐藏它，让所有部署都走
  `openfuyao_prepare` / `openfuyao_deploy`。
- sidecar 复用宿主上的 `bke`、`kubectl`、`helm` 和 `sudo -n`，与 Python 服务的行为完全
  一致，不会额外提权。
- `auto` 在鉴权/版本/服务端错误上一律不回退，避免双写者。

## 已知限制

- sidecar 用自己的数据库，因此看不到由另一份 `witty-service` 数据库创建的环境。要接管
  既有状态，先停掉旧服务，把它的 SQLite 文件复制到 `$dataDir/sidecar.sqlite3`（只能有
  一个写者），或者改用 `mode: external`。
- `openfuyao_status` 是从控制台发现资源的。在 `sidecar` 模式下，这可能把另一个部署创建的
  集群/应用也一并发现；永远不要在同一台宿主机上同时运行 sidecar 和另一个编排者。
- 预检与部署依赖 Python 实现所要求的宿主机工具和免密 sudo。
- 控制台是以 URL 形式返回、在新标签页里打开的；右侧边栏面板只汇总状态，不内嵌控制台。
