# 分发与在另一台机器上安装 DSH openFuyao 插件

这份文档面向“另一台机器环境与当前一致”的场景：同样的 Linux 发行版和 CPU
架构、同样版本的 DSH、已安装 `dsh-better-sidebar`，并且宿主机具备 openFuyao
所需的 `bke`、`kubectl`、`helm` 和免密 `sudo`。

插件由两个 DSH bundle 组成：

| 目录 | 包名 | 作用 |
| --- | --- | --- |
| `dsh-plugin/` | `@openwitty/dsh-openfuyao` | Host 工具、传输选择、sidecar 生命周期 |
| `dsh-plugin/panel/` | `@openwitty/dsh-openfuyao-panel` | 右侧边栏面板（`dsh-better-sidebar` tab） |

两个 bundle 必须一起安装。拆开是因为 DSH 在启动时缓存 `dsh.client` 元数据：
一个已经以 Host-only 方式挂载的包，无法在热重载中补上 Client 半区。

## 1. 生成可分发包

在源机器仓库根目录执行：

```bash
./scripts/package-dsh-plugin.sh
```

输出：

```text
dist/dsh-openfuyao-0.1.0-linux-aarch64.tar.gz
dist/dsh-openfuyao-0.1.0-linux-aarch64.tar.gz.sha256
```

校验（在 `dist/` 目录内执行）：

```bash
sha256sum -c dsh-openfuyao-0.1.0-linux-aarch64.tar.gz.sha256
```

压缩包内是：

```text
dsh-openfuyao-0.1.0-linux-aarch64/
  dsh-plugin/                  # Host bundle + panel/ + sidecar/
  INSTALL.md                   # 本文件
  BUILD-INFO.txt               # 版本、构建机、sidecar 架构
```

`sidecar/` 约 70 MB（onedir，含 Python 运行时和 Alembic 脚本）。PyInstaller
产物不能跨架构，`aarch64` 的包只能装到 `aarch64`；`x86_64` 机器需要在目标机
重新构建：

```bash
uv pip install --python .venv/bin/python 'pyinstaller>=6.10'
./scripts/build-sidecar.sh
rm -rf dsh-plugin/sidecar
cp -a build/sidecar-dist/witty-openfuyao-sidecar dsh-plugin/sidecar
```

如果目标机已经有可用的 `witty-service`，也可以不带 sidecar，直接把插件配置成
`mode: external`；此时 Host bundle 不需要 `sidecar/` 目录。

## 2. 复制并安装

把压缩包复制到目标机并解压，例如：

```bash
sudo mkdir -p /opt/dsh-openfuyao
sudo tar -C /opt/dsh-openfuyao --strip-components=1 -xzf dsh-openfuyao-0.1.0-linux-aarch64.tar.gz
sudo chown -R "$USER" /opt/dsh-openfuyao
```

然后在目标机的 DSH 会话里让 agent 执行（不是 shell 命令）：

```text
plugin_manager install_bundle target=/opt/dsh-openfuyao/dsh-plugin
plugin_manager install_bundle target=/opt/dsh-openfuyao/dsh-plugin/panel
```

安装完成后确认两条 profile 插件行是 active：

```text
plugin_manager list_bundles
```

期望看到：

```text
@openwitty/dsh-openfuyao
@openwitty/dsh-openfuyao-panel
```

以及 `include:openfuyao`、`include:openfuyao-panel` 两条 Loader 行。

> 本地目录安装是 `link:` 语义：目标机后续修改 `/opt/dsh-openfuyao` 下的文件会
> 直接生效（Host 代码需要 reload 插件，Client 代码会走 HMR）。如果要固定版本，
> 把目录复制到只读位置，升级时重新打包安装。
>
> 只刷新页面而不 reload 插件时，新的 Client 可能去调用旧 Host 没注册的 POST
> 路由（例如 `/openfuyao/api/preflight`）；该请求会落到 Web 静态兜底并得到
> 405。面板会退回 `POST /openfuyao/api/plan` 继续刷新预检，但升级后仍应
> reload 插件，让 Host 与 Client 版本一致。
>
> **升级时不要直接覆盖正在运行的 sidecar 二进制**：Linux 会报
> `Text file busy`。建议解压到新目录（例如 `/opt/dsh-openfuyao-0.1.0-ux`），
> 再用 `install_bundle` 指向新目录，然后 reload 插件或重启 DSH；旧目录保留，
> 随时可以切回。面板新代码调用的 `GET /openfuyao/api/logs` 也要求 Host 已
> reload；只刷新页面时日志区会显示“日志暂不可用”，其余功能不受影响。

## 3. 选择传输模式

插件默认 `mode: auto`：

- `127.0.0.1:8000` 有可用的 `witty-service` → 使用外部后端；
- 端口没有监听 → 启动内置 sidecar；
- 端口在监听但返回 401/403/500 或缺少 `/openfuyao` API → **报错，不启动
  sidecar**。这是为了避免两个写者对同一个 openFuyao 状态机/数据库并发操作。

在 profile 的 `cordis.patch.yml` 覆盖：

```yaml
- id: openfuyao
  name: "@openwitty/dsh-openfuyao"
  config:
    mode: auto
    baseUrl: http://127.0.0.1:8000
    agentName: openfuyao-deployer
    requireApproval: true
    panelDeploy: true
```

`panelDeploy: false` 会隐藏面板里的“确认部署”，只允许通过
`openfuyao_prepare` / `openfuyao_deploy` 工具部署（仍受工具审批门控）。

| 场景 | 建议 |
| --- | --- |
| 目标机已有 `witty-backend.service` | `mode: external`，不要在 8000 端口之外再起 sidecar |
| 目标机是干净机器，没有后端 | `mode: sidecar`，sidecar 自己建私有 SQLite |
| 两种都可能 | `mode: auto`（默认） |

### 外部模式的 token

外部模式按以下顺序取 token：

1. patch 里的 `token`；
2. 环境变量 `AUTH_TOKEN`；
3. `tokenFile`（默认 `/etc/witty-service/witty-service.env`）里的 `AUTH_TOKEN=`。

token 只存在 Host 进程，浏览器永远拿不到。

### 内置 sidecar 的 agent

sidecar 使用 `agentName` 通过 `/agents` 解析 agent id。如果目标机的数据库是从
别的机器复制来的，必须显式指定原数据库里的 agent UUID：

```yaml
- id: openfuyao
  name: "@openwitty/dsh-openfuyao"
  config:
    mode: sidecar
    agentName: openfuyao-deployer
    agentId: 46083619-6933-440c-92c4-ae8570bc003b
    dataDir: /var/lib/dsh-openfuyao
```

否则会出现“环境存在但列表为空”的假象：查询用了新生成的 agent id，和数据库里
原有记录的 agent id 对不上。

## 4. 接管已有数据库（单写者）

sidecar 默认使用自己的数据库：

```text
$dataDir/sidecar.sqlite3
```

要把旧 `witty-service` 的状态带过来：

```bash
# 1) 先停旧服务，确保没有第二个写者
sudo systemctl stop witty-backend.service

# 2) 确认进程已退出
pgrep -af 'witty|uvicorn' || true

# 3) 复制 SQLite 主文件（WAL 模式下建议停服后复制，或同时复制 -wal/-shm）
sudo mkdir -p /var/lib/dsh-openfuyao
sudo cp /var/lib/witty-service/.witty/db/witty_service.sqlite3 \
        /var/lib/dsh-openfuyao/sidecar.sqlite3
sudo chown -R "$USER" /var/lib/dsh-openfuyao

# 4) 校验
sqlite3 /var/lib/dsh-openfuyao/sidecar.sqlite3 'pragma integrity_check;'
```

然后把 `dataDir` 指到 `/var/lib/dsh-openfuyao`，并在 profile patch 里固定
`agentId`。**不要**在 sidecar 运行时再启动 `witty-backend.service`；两者同时
写同一个 host 的 openFuyao 状态会破坏单写者假设。

恢复旧服务时：

```text
plugin_manager set_bundle target=@openwitty/dsh-openfuyao enabled=false
# 等待 pgrep -af witty-openfuyao-sidecar 为空
# 恢复原 cordis.patch.yml
systemctl start witty-backend.service
plugin_manager set_bundle target=@openwitty/dsh-openfuyao enabled=true
```

面板 bundle 可以不关；它不拥有 sidecar，只调用 Host 路由。

## 5. 验证

在目标机的 DSH 会话里：

```text
openfuyao_status
openfuyao_environments
```

右侧边栏 `+` 菜单应出现 **openFuyao 部署** / **openFuyao**。打开后应看到环境、
业务集群、应用和 issues；点击 issue 上的 **询问 DSH**，问题会被追加到当前会话
的输入框（不会自动发送）。

如果目标机还没有 ready 环境，面板会显示宿主机预检（通过/警告/失败）以及
**重新预检** / **确认部署**。确认部署需要勾选确认框，Host 路由会重新预检、创建
环境并启动 Bootstrap；部署中面板显示当前阶段、已用时和 `bootstrap.log` 实时
日志，取消部署前会再次确认。

如果工具可用但面板不出现：

1. 确认 `dsh-better-sidebar` 已安装且 active；
2. 刷新页面一次，让 Client bundle 重新注册 tab；
3. 检查 `sidebar.right.pane.tab` 是否有 `dsh-better-sidebar:openfuyao:overview`。

## 6. 应用安装/删除（Q2）

DSH 不需要再包一层 CLI。插件已经把这些能力暴露成模型工具：

```text
openfuyao_app_preflight   # 只读：集群/chart/namespace/端口检查
openfuyao_app_install     # 安装 Helm release
openfuyao_apps            # 轮询应用状态
openfuyao_logs            # 读取 Pod/安装日志
openfuyao_app_rollback    # 回滚 revision
openfuyao_app_uninstall   # 删除 Helm release
```

典型对话：

> 在集群 `bke-cluster` 上安装 `nginx`，release 名 `web`，namespace `demo`，
> 用本地 chart `/opt/charts/nginx`，安装前先预检。

agent 会先调 `openfuyao_app_preflight`，再调 `openfuyao_app_install`，随后用
`openfuyao_apps` / `openfuyao_logs` 验证。删除/回滚同样走工具：

```text
openfuyao_apps
openfuyao_app_uninstall app_id=<应用 id>
openfuyao_app_rollback app_id=<应用 id> revision=<可选>
```

不需要在 shell 里拼 `witty-service openfuyao app ...`，也不需要把 token 暴露给
shell；工具和 CLI 最终调用同一个 REST 编排层。

注意：这些是 **mutating tools**，默认受 `requireApproval: true` 门控。当前这台
测试机的会话关闭了审批，所以工具调用会被自动拒绝；在目标机测试时要么打开审批，
要么只在一次性实验环境里设 `requireApproval: false`。

## 7. 卸载

```text
plugin_manager set_bundle target=@openwitty/dsh-openfuyao-panel enabled=false
plugin_manager set_bundle target=@openwitty/dsh-openfuyao enabled=false
plugin_manager remove_bundle target=@openwitty/dsh-openfuyao-panel
plugin_manager remove_bundle target=@openwitty/dsh-openfuyao
```

卸载前先停 sidecar（禁用 Host bundle 即可），确认 `pgrep -af
witty-openfuyao-sidecar` 为空。`plugin-data/` 下的 sidecar 数据库不会自动删除，
需要保留迁移或手工清理。

## 8. 分发检查清单

- [ ] 目标机 CPU 架构与 sidecar 一致（`file dsh-plugin/sidecar/witty-openfuyao-sidecar`）
- [ ] DSH 版本与源机器一致（当前 `0.2.1-rc.2`）
- [ ] `dsh-better-sidebar` 已安装（当前 `0.28.0`）
- [ ] 目标机有 `bke`/`kubectl`/`helm`/免密 `sudo`（sidecar 模式）
- [ ] 没有同时运行旧 `witty-backend.service` 和 sidecar
- [ ] 如果复制数据库，已停旧服务并校验 `pragma integrity_check`
- [ ] 复制数据库时固定了原 `agentId`
- [ ] 安装后 `openfuyao_status` 和右侧面板都能读到同一份状态
