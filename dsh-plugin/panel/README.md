# openFuyao 右侧边栏面板

`@openwitty/dsh-openfuyao` 的纯客户端配套包。它通过
`ctx.betterSidebar.registerTab` 向 `dsh-better-sidebar` 注册一个 tab；由后者把这个 tab
放进 DSH 原生的右侧边栏及其 **+** 菜单。

这个 tab 读取 `GET /openfuyao/api/overview`，那是主 bundle 提供的 Host 路由。浏览器始终
拿不到 sidecar 的临时端口和 bearer token。

面板里每个问题都有一个 **询问 DSH** 按钮。它会把一段结构化诊断 prompt（问题码、严重级别、
相关的环境/集群/应用状态、观测时间、传输方式）通过
`ctx.conversation.input.for(ctx.sessions.scope(sessionId))` 追加到当前会话的输入框。它只
填充草稿，是否发送由用户决定。

没有 ready 环境时，这个 tab 变成部署视图：

- `GET /openfuyao/api/plan` 执行只读的宿主机预检，返回检查项与警告（不再渲染静态的 plan
  列表）；
- **重新预检** 调用 `POST /openfuyao/api/preflight`（按环境），或重新跑 dry-run plan；
- **确认部署** 先显示一个显式的确认勾选框，然后带 `confirm: true` 调用
  `POST /openfuyao/api/deploy`；由 Host 路由创建环境并启动 Bootstrap；
- 处于 `bootstrapping` / `waiting_console` 期间，面板轮询
  `GET /openfuyao/api/environments` 显示当前阶段和计时器，并用
  `GET /openfuyao/api/logs?environment_id=…&tail=1` / `…&cursor=…` 增量追加
  `bootstrap.log` 的实时尾部输出；**取消部署**（`POST /openfuyao/api/cancel`）会先要求确认。

部署视图是用户主动发起的动作，与模型工具审批门禁相互独立。把插件配置里的 `panelDeploy`
设为 `false` 可以隐藏部署按钮，让部署只走 `openfuyao_prepare` / `openfuyao_deploy`。

## 安装

不需要单独安装：Host 包（`dsh-openfuyao`）把本包作为普通依赖带入，并在自己的
`cordis.patch.yml` 里插入 `openfuyao-panel` 行。装完 Host 后打开右侧边栏的 **+**
菜单，选 **openFuyao / openFuyao 部署** 即可。

本包仍与 Host 分成两个 npm 包，是因为 DSH 在启动时会缓存一个包的 `dsh.client` 元数据：
给一个已经以 Host-only 方式挂载的包补 Client 半区，需要重启 DSH。

依赖 `dsh-better-sidebar`。没有它时 Client 半区保持非激活（它注入 `betterSidebar`），而
Host 工具仍然可用。
