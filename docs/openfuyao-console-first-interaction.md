# openFuyao 控制台优先交互（2026-10-21）

> 本文覆盖阶段 2/3 的新分工。旧文档中“Agent 用 `cluster create` 建业务集群”的描述
> 仅作为历史实现保留，不再是产品路径。

## 1. 新分工

| 阶段 | 入口 | PolyMind 的职责 |
| --- | --- | --- |
| 阶段 1 引导节点 | 对话 / 面板“部署” | 自动 Bootstrap、预检、等待控制台 |
| 阶段 2 业务集群 | **只允许**引导节点控制台手动创建 | 只读感知、纳管、诊断；不代建 |
| 阶段 3 应用 | 业务控制台手动安装，或对话自然语言安装 | 感知手工安装、预检、安装、诊断、回滚/卸载 |

阶段 2 的 CLI `witty-service openfuyao cluster create` 已停用（执行会提示改去控制台），
`POST /openfuyao/clusters` 也返回 `409 CLUSTER_CREATE_DISABLED`；`cluster list/status/logs`
仍保留，用于感知和排障。

## 2. 面板两个 Tab

1. **快速入门**：只放三步骤、诊断和感知状态，不再内嵌控制台。
   - 第 1 步：引导节点初始化（自动）；
   - 第 2 步：新增业务集群（按钮切到“引导节点控制台”tab，不提供“让 Agent 创建”）；
   - 第 3 步：安装应用（切到“业务集群”tab，或在对话里让 PolyMind 安装）。
2. **引导节点控制台**：独立 tab，嵌入 `https://<引导节点>:30010/`，占满面板高度。
3. **业务集群**：业务集群控制台。
   - 有 ready 集群时嵌入 `https://<node>:<ingress-nodeport>/`；
   - 没有就绪集群时提示去“引导节点控制台”创建；
   - 右上角保留“在浏览器打开”兜底。
   - Web 端受自签 HTTPS 限制，不强行 iframe（避免白屏），只给“在浏览器打开”。

控制台地址由后端实时发现，桌面端**不写死端口、也不改写 host**：OAuth state 和
`sessionID` Cookie 都按 host 绑定，改写 host 会让登录回调落到另一个 host。
两个控制台使用独立 `partition`（`persist:polymind-console` /
`persist:polymind-console-business`）；它们都有同名的 `sessionID`/`wsID` Cookie，
而 Cookie 不区分端口，共用 partition 会互相顶掉登录态。

快速入门的状态、集群数、应用数、异常数都来自真实感知，不是 localStorage 勾选。

## 3. 感知：控制台改动如何进入 PolyMind

`GET /openfuyao/overview?agent_id=...` 每次刷新会：

1. 从管理面 `BKECluster` / `BKENode` 读取**所有**业务集群（包括控制台手工创建的）；
2. 从 `<cluster>-kubeconfig` Secret 取业务 kubeconfig（写入受控目录，0600）；
3. 从业务集群 `helm list -A -o json` 读取 release（包括控制台/命令行手工安装的）；
4. 从 Pod 的 `waiting.reason` 读取异常（ImagePullBackOff / CrashLoop / Pending 等）；
5. 按名称幂等纳管到 `openfuyao_clusters` / `openfuyao_apps`，不重复插入；
6. 返回 `clusters`、`apps`、`issues`、`console`、`discovered`、`errors`。

管理面已删除、但数据库还存在的集群/应用会被标记为失败并带
`CLUSTER_NOT_FOUND` / `APP_NOT_FOUND`，不会静默消失。

### 诊断结论

`issues[]` 字段：`severity`（info/warn/error）、`source`（environment/cluster/node/app）、
`code`、`title`、`message`、`remediation`、`resource_id/name`。

已覆盖：

- 环境预检 warn/fail；
- 集群未 Ready、节点未 Ready、控制台已删除；
- 应用 release 失败、Pod 未就绪；
- `ImagePullBackOff`：提示检查镜像源，Bitnami 非官方镜像需
  `global.security.allowInsecureImages=true`，离线环境改本地 harbor / `--image`；
- `CrashLoopBackOff`、`Pending` 等。

## 4. Agent 如何回答“现在有什么/为什么坏了”

Agent 的 `AGENTS.md` 和两个 skill 已更新：

```bash
witty-service openfuyao observe --json
```

必须先执行这条命令，再根据 `clusters/apps/issues` 回答；不能猜。回答结构：

```text
现象 → 根因判断 → 处理建议（命令/控制台路径）→ 影响面 → 回滚方案
```

能直接修复的，先复述影响面并征得用户确认；不能确认的只给建议。

## 5. 阶段 3 预检 / 安装 / 回滚

```bash
# 预检（集群 Ready、kubeconfig、chart 来源、release 冲突、NodePort 占用）
witty-service openfuyao app preflight \
  --cluster bke-nl --release nginx \
  --chart-dir /path/to/chart --image <可达镜像> --node-port 30080 --json

# 安装
witty-service openfuyao app install ... --confirm --wait --json

# 回滚（默认上一 revision；也可 --revision N）
witty-service openfuyao app rollback --cluster bke-nl --release nginx --confirm --json

# 卸载
witty-service openfuyao app uninstall --cluster bke-nl --release nginx --confirm --json
```

手工在控制台安装的 release 被 `observe` 纳管后，同样可以用这两条命令回滚/卸载。

## 6. 当前边界

- 业务集群仍只支持“本地 1 master + 已有 worker”，多 master/扩容未支持；
- 业务控制台是自签 HTTPS，Web 端 iframe 可能被证书/浏览器策略拦截，桌面端
  webview 优先；两种模式都保留“在浏览器打开”；
- Web 端 nginx 控制台网关必须保留 Host 的端口（`$http_host`）。控制台登录 POST 会做
  CSRF 的 Origin/Host 比对，`$host` 丢掉 `:3002` 会让登录成功后仍提示 cookie 过期；
- `cluster create` 的后端 API 也已返回 `409 CLUSTER_CREATE_DISABLED`；产品 UI、
  Agent prompt、skill 和 CLI 均不再提供该入口；
- 应用回滚依赖 Helm history；只有 1 个 revision 时会明确报
  `APP_ROLLBACK_FAILED`，不会假装成功；
- 感知依赖管理面/业务集群可达；不可达时 `discovered=false` 或 `errors[]` 会说明，
  不会把“查询失败”当成“没有资源”。

## 7. 验收命令

```bash
# 手工在控制台建一个集群/装一个应用后：
curl -s -H "Authorization: Bearer $AUTH_TOKEN" \
  "http://127.0.0.1:8000/openfuyao/overview?agent_id=<agent-id>" | jq

# Agent 侧
witty-service openfuyao observe --json
witty-service openfuyao app preflight --cluster <name> --release <name> \
  --chart-dir <path> --node-port 30080 --json
```

期望：`clusters` 包含控制台新建的集群，`apps` 包含手工安装的 release，
`issues` 能指出失败的 Pod，并给出可执行 remediation。

## 8. 2026-10-21 面板问题修复

| 现象 | 根因 | 修复 |
| --- | --- | --- |
| 引导节点控制台登录成功后立刻提示“您尚未登录或您的登录会话已超时” | 桌面端把控制台 host 改写成了 `127.0.0.1`，而 OAuth state / `sessionID` Cookie 都按 host 绑定；同时两个控制台共用 partition，同名 Cookie（`sessionID`/`wsID`）在**同 host 不同端口**下会互相覆盖 | 不再改写 host，直接使用后端返回的 `https://<node>:<port>/`；引导节点与业务集群控制台使用独立 partition（`persist:polymind-console` / `persist:polymind-console-business`） |
| 业务集群控制台白屏；点“重载控制台”后 PolyMind 也白屏 | 主进程只放行固定 30010 端口，业务集群的 ingress NodePort 是随机的（本环境 31616），`<webview>` 被 `will-attach-webview` 拦截；`webview.reload()` 在未挂载的 guest 上会抛异常并冒到 React root | 渲染进程把后端发现的控制台地址注册给主进程，主进程按注册结果放行 webview 与自签证书；每个控制台独立 partition；`reload()` 加就绪判断和 try/catch，并加控制台级 Error Boundary |
| 快速入门内容拥挤 | 3 步骤、诊断和引导节点控制台挤在同一个 tab | 拆成三个 tab：快速入门（步骤 + 诊断）、引导节点控制台、业务集群 |

Web 端业务控制台不再强行 iframe（自签 HTTPS 会被浏览器拦成白屏），改为提示“在浏览器打开”；
桌面端仍直接内嵌。

## 9. 2026-10-22 引导节点控制台登录态问题（历史）

### 现象

在 PolyMind 里打开“引导节点控制台”（`https://<node>:30010/`），登录页能正常出现；
输入账号密码后 OAuth 回调返回 200，但控制台立刻弹出“您尚未登录或您的登录会话已超时”，
再登录仍然重复，永远进不了总览页。

### 当时的判断

`30010` 上可能挂着上一套管理集群遗留的 console-service：登录页能开、OAuth 回调也
返回 200，但会话写不进去，控制台随后会自己删掉 session。

### 当时的修复（已回退）

**① 让 `30010` 复用业务集群的 ingress-nginx**：在业务集群创建 NodePort Service
`ingress-nginx-guide`，把宿主机 `30010` 指向业务 ingress。

**② 后端探测 + 前端回落**：`GET /openfuyao/overview` 增加 `guide_console` 字段，
当 `session_capable === false` 时把引导节点 tab 自动换成业务控制台地址。

这两个修复叠加后，`30010` 和 `31616` 变成了**同一个 ingress、同一套 console-service**，
引导节点控制台与业务集群控制台因此显示为同一个页面。① 已删除，② 已改为只诊断、
不再切换地址，详见下一节。

## 10. 2026-10-22 引导节点与业务集群控制台显示为同一个

### 现象

面板里“引导节点控制台”和“业务集群”两个 tab 看到的登录页、总览和登录态完全一样，
切换 tab 没有任何区别。

### 根因

两层原因叠加，缺一不可：

1. **环境层：`30010` 被业务集群的 `ingress-nginx-guide` 抢占。**
   管理 k3s 跑在 nerdctl 容器里，`nerdctl run -p 30010:30010` 本来把宿主机 `30010`
   DNAT 到管理集群 ingress（`10.4.0.10:30010`）。但业务集群又创建了一个
   NodePort=30010 的 Service；宿主机 `KUBE-SERVICES` 链在
   `CNI-HOSTPORT-DNAT` **之前**，所以 `30010` 先被 kube-proxy 抢走，落到业务集群
   ingress（即 `31616` 的同一个后端）。两个端口自此指向同一套 console-service。
2. **代码层：探测误判 + 自动回落。**
   老版本 `bke-console-service` 对任意随机 `sessionID` 都返回
   `401 cookie not found`，和完全没带 Cookie 的响应一模一样。旧探针把
   `cookie not found` 一律当成“入口丢 Cookie”，于是 `session_capable=false`；
   前端再把引导节点 tab 的地址替换成 `console.url`（业务控制台）。
   即使环境层没被抢占，这一层也会把两个 tab 合并。

可以用 OAuth cookie 名快速区分两套控制台：管理集群是 `csrf_bke` / `idpLogin_bke`，
业务集群是 `csrf` / `idpLogin` / `X-OpenFuyao-Referrer`。

### 修复

**① 环境：删除业务集群里的 `ingress-nginx-guide`，把 `30010` 还给管理集群。**

```bash
kubectl --kubeconfig /etc/kubernetes/admin.conf -n ingress-nginx \
  delete svc ingress-nginx-guide

# 期望：guide 返回 csrf_bke，business 返回 csrf
curl -sk -L -c /tmp/g.cookies -o /dev/null https://<node>:30010/
curl -sk -L -c /tmp/b.cookies -o /dev/null https://<node>:31616/
grep -oE 'csrf_bke|csrf' /tmp/g.cookies /tmp/b.cookies
```

删除后，宿主机 `30010` 会回落到管理 k3s 容器的端口映射
（`10.4.0.10:30010`）；管理控制台自身的登录态问题需要单独修，**不能**再用
“把 30010 指到业务 ingress”的方式绕过，否则又会合并两个控制台。

**② 代码：探针只在能证明 Cookie 被读到时报 `true`，无法区分时报 `null`。**

对同一个 `/rest/auth/user` 发两次请求：一次带随机 `sessionID`，一次不带。

| 带 Cookie 的响应 | 匿名响应 | 结论 |
| --- | --- | --- |
| 401 `cannot get token from sessionID` | 401 `cookie not found` | `true`（`cookie_forwarded`） |
| 与匿名响应不同（例如不同的错误文案） | 401 `cookie not found` | `true`（`session_cookie_observed`） |
| 401 `cookie not found`，且与匿名响应完全相同 | 401 `cookie not found` | `null`（`session_cookie_unobservable`） |

`null` 表示“无法判断”，不再武断地给 `false`。老版本 bke-console 就是这一档，
它实际上是正常的，只是对未知会话固定回 `cookie not found`。

**③ 代码：前端不再自动替换控制台地址。**

- 引导节点 tab 永远使用 `environment.console_url`（`https://<node>:30010`），
  partition 固定 `persist:polymind-console`，webview variant 固定 `guide`；
- 业务集群 tab 永远使用后端发现的 `console.url`（`https://<node>:<ingress-nodeport>/`），
  partition 固定 `persist:polymind-console-business`，variant 固定 `business`；
- `session_capable` 只作为诊断字段，不再驱动 UI 切换。两个控制台即使其中一个登录
  有问题，也不会显示成另一个。

### 验收

```bash
# 两个地址必须落到不同控制台
curl -sk -L -c /tmp/g.cookies -o /dev/null https://<node>:30010/
curl -sk -L -c /tmp/b.cookies -o /dev/null https://<node>:31616/
grep -oE 'csrf_bke|csrf' /tmp/g.cookies /tmp/b.cookies

# overview 里 console.url 是业务控制台，guide_console.url 是引导节点控制台
curl -s -H "Authorization: Bearer $AUTH_TOKEN" \
  "http://127.0.0.1:8000/openfuyao/overview?agent_id=<agent-id>" | jq '{console, guide_console}'
```

期望：`console.url` 以 `:31616`（或当前 ingress NodePort）结尾，`guide_console.url`
以 `:30010` 结尾；两个 tab 登录后各自保持独立会话。

如果修复 ① 后引导节点控制台仍然反复提示“登录会话已超时”，那是管理集群
console-service / plugin-management 的登录态问题，应查管理集群日志：

```bash
kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n openfuyao-system \
  logs deploy/console-service --tail=100
```

不要再通过改写 `30010` 或自动切换地址来掩盖它。具体根因与修复见第 12 节。

## 11. 顺带：右侧面板全屏

- 右上角新增“全屏面板 / 退出全屏”按钮（`Maximize2` / `Minimize2`，`aria-pressed`）；
- 面板保持同一个 DOM 节点，`position: fixed; inset: 0`，对 `top/left/width/height`
  做 280ms `cubic-bezier(0.22,1,0.36,1)` 过渡；
- 尊重 `prefers-reduced-motion`；`Escape` 退出；`busy` 期间禁用按钮防连点；
- `<webview>` 的 guest 表面在连续 resize 时比 CSS 帧慢约 0.5s，因此过渡期间
  先把控制台区域淡出（`data-panel-animating` + `data-console-webview`），
  等面板尺寸落定后再淡入，避免“外壳展开了、控制台还停在旧宽度”的撕裂；
- 退出时用父级 `ResizablePanel` 的矩形作为目标，动画结束后再切回文档流，
  因此不会有一帧闪烁。

## 12. 2026-10-22 引导节点控制台登录后仍提示“您尚未登录或登录会话已超时”

### 现象

在引导节点 tab 里能打开登录页，输入 admin 后也能跳到控制台地址，但页面立刻弹出：

> 您尚未登录或您的登录会话已超时，请重新登录

点“确定”后回到登录页。业务集群 tab 不受影响。

### 根因

不是控制台前端、不是 Cookie、也不是 console-service 的会话存储，而是**管理 k3s apiserver 的认证 webhook 解析不到服务名**。

管理 k3s 的 apiserver 启动参数里有：

```text
--authentication-token-webhook-config-file=/var/lib/rancher/k3s/webhook/webhook-config.yaml
```

该文件里写的是：

```yaml
server: https://oauth-webhook.openfuyao-system.svc.cluster.local:9095/oauth/tokenauth/fuyao
```

但 apiserver 跑在 nerdctl 的 `kubernetes` 容器里，容器的 `/etc/resolv.conf` 只有：

```text
nameserver 192.168.122.1
```

它不经过 CoreDNS，无法解析 `*.svc.cluster.local`。apiserver 日志会反复出现：

```text
Failed to make webhook authenticator request:
Post "https://oauth-webhook.openfuyao-system.svc.cluster.local:9095/oauth/tokenauth/fuyao?timeout=30s":
dial tcp: lookup oauth-webhook.openfuyao-system.svc.cluster.local: no such host

"Unable to authenticate the request" err="[invalid bearer token, ... no such host]"
```

完整链路是：

1. 登录成功后 console-service 把 OAuth access token 存进会话；
2. 控制台加载后请求 `/clusters/host/rest/plugin-management/v1beta1/consoleplugins`；
3. console-service 把会话里的 token 作为 `Authorization: Bearer` 转发给 `kubernetes.default.svc`；
4. apiserver 调认证 webhook 校验 token，但域名解析失败，返回 401；
5. 控制台前端的全局 401 拦截器会 `POST /rest/auth/logout`，清掉 `sessionID_bke`，再弹“您尚未登录…”。

所以“登录成功”和“马上掉线”同时成立。业务集群能正常用，是因为业务集群 kube-apiserver 的 webhook 地址在它自己的环境里可解析。

### 修复

**① 把 webhook 地址改成 oauth-webhook Service 的 ClusterIP，并保留 TLS 的 SNI。**

先取 ClusterIP：

```bash
kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n openfuyao-system \
  get svc oauth-webhook -o jsonpath='{.spec.clusterIP}'
```

备份并修改 `/var/lib/rancher/k3s/webhook/webhook-config.yaml`：

```yaml
clusters:
  - name: oauth-webhook
    cluster:
      certificate-authority: /var/lib/rancher/k3s/webhook/ca.pem
      server: https://100.10.65.37:9095/oauth/tokenauth/fuyao
      tls-server-name: oauth-webhook.openfuyao-system.svc.cluster.local
```

`tls-server-name` 不能省：oauth-webhook 的服务端证书只有 DNS SAN
（`oauth-webhook.openfuyao-system.svc.cluster.local` 和 `...pod.cluster.local`），
没有 IP SAN；直接连 IP 会因主机名校验失败。

**② 重启管理 k3s 容器，让 apiserver 重新读取该文件。**

```bash
nerdctl restart kubernetes
```

**③ 不要把“在容器的 `/etc/hosts` 里加一行”当成最终方案。**

临时加 hosts 能立刻验证问题，但容器重建后会丢，而且下次排障时很容易误以为
webhook 配置已经正确。最终修的是 `webhook-config.yaml` 本身。

### 验收

```bash
# 1) 不再有解析失败
nerdctl logs --since 5m kubernetes 2>&1 | grep -c 'no such host'   # 期望 0

# 2) 登录后关键接口 200
#    在控制台 webview 里登录后，Network 应看到：
#    GET /clusters/host/rest/plugin-management/v1beta1/consoleplugins -> 200
#    GET /clusters/host/proxy/cluster/dist/cluster.mjs -> 200
#    页面最终落到 /container_platform/cluster/cluster，且不再弹窗。
```

本环境验证结果：修复后 `consoleplugins` 与 `/clusters/host/proxy/...` 均为 200，
页面显示 `bke-nl / 管理集群` 的集群列表；刷新页面登录态保持。业务集群 `31616`
仍是独立的 `sessionID` 会话，未受影响。

### 注意

- 升级 openFuyao 后安装器可能重写 `/var/lib/rancher/k3s/webhook/webhook-config.yaml`，
  升级后要复查 `server` 和 `tls-server-name`。
- 如果 `oauth-webhook` Service 被删除重建、ClusterIP 变化，要同步更新该文件并重启
  `kubernetes` 容器。
- 不要用“清空控制台 Cookie、重装 console-service、把 30010 指回业务 ingress”
  绕过：它们都解释不了 apiserver 日志里的 `no such host`，而且会把已经分开的两个
  控制台再次合并。
