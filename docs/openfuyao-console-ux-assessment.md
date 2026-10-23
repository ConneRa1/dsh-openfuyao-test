# 双控制台在 PolyMind 中的承载方式评估

> 问题：PolyMind 只内嵌了管理控制台（30010），但阶段 2 建集群、阶段 3 装应用分别涉及管理控制台和业务控制台（31616）。
> 是否要在 openFuyao tab 里再加一块，或者干脆把所有网页访问都改成浏览器 tab？

---

## 1. 事实核查

| 事实 | 依据 |
| --- | --- |
| 30010 是管理控制台，唯一插件是 `cluster`（集群生命周期管理） | `GET /rest/plugin-management/v1beta1/consoleplugins` 只返回 `cluster / 集群生命周期管理 / /container_platform` |
| 31616 是业务集群内 console 的 ingress NodePort，应用市场等插件在这个集群里 | 阶段 3 实跑：应用市场 repo/chart/release API 都在 31616 上操作 |
| 两个控制台是**两个独立实例**，不是同一实例的两个视图 | 管理 k3s 与业务集群各自有 console-service / oauth-server / user-management |
| Cookie 名不同，同 host 不同端口可共存 | 管理端：`sessionID_bke/wsID_bke/csrf_bke/idpLogin_bke`；业务端：`sessionID/wsID/csrf/idpLogin` |
| 管理控制台本身是**多集群壳**：按集群拼接插件与 API 地址 | bundle 中 `consolePluginUrl: /clusters/${cluster}/rest/plugin-management/v1beta1/consoleplugins`，以及 `/clusters/${cluster}/rest/marketplace/...`、`/rest/application-management/...` |
| PolyMind 目前只代理 30010 | `nginx.conf` 3002 → `https://127.0.0.1:30010`，剥 `X-Frame-Options`/CSP，改 Secure/SameSite Cookie |
| 面板第 2/3 步是 localStorage 里的人工勾选，不是真实状态 | `quick-start-checklist.tsx` 的 `pm_openfuyao_manual_steps:<envId>` |

关键结论：**“两个控制台”更像“一个多集群壳 + 一个集群内直连入口”**。管理控制台在选中某个集群后会去拉该集群的插件
（`/clusters/<name>/rest/plugin-management/...`），也就是说应用市场很可能可以在 30010 内进入，31616 只是同一套 UI 的
集群内入口。这一点需要在有业务集群时实机确认（见 §6），当前管理 k3s 已被 reset 成空集群，无法直接验证。

---

## 2. 方案评估

### 方案 A：openFuyao tab 内再加一块（双 iframe / 双区块）

技术上可行：

- 再起一个 nginx server（如 3003）反代 31616，剥 frame 头、改 Cookie 标志；
- 两个控制台 Cookie 名不同，端口不同（Cookie 不区分端口，但名字不同）不会互相顶号；
- 业务控制台只在阶段 2 完成后存在，需要可用性探测与空态。

但不推荐作为默认形态：

1. **面板空间不够**：右侧面板宽度有限，两个完整 SPA 上下/左右排布会互相挤压，滚动、弹窗、路由都难受；
2. **双 OAuth 双登录**：用户要在同一面板里登录两次，切换时上下文丢失；
3. **代理面翻倍**：每个控制台都要处理 TLS、Origin 校验、`redirect_uri`、Cookie、WebSocket、HSTS、上游升级；
   我们已经为 30010 踩过一遍，再复制一遍等于把维护成本乘二；
4. **与自动化方向相反**：产品目标是让用户不用进控制台，双内嵌是把这个方向做反了。

结论：可作为“演示/应急”开关，不做默认。

### 方案 B：去掉 iframe，所有网页访问都用浏览器 tab

最稳、最省事：

- 不做代理，就不需要处理 `X-Frame-Options`、CSP、Secure Cookie、Origin 校验、HSTS、redirect；
- 控制台获得完整浏览器体验（全屏、快捷键、DevTools），上游升级几乎无感。

代价：

1. **可达性**：如果 PolyMind 是通过 SSH 隧道/端口转发访问的，浏览器到不了 `192.168.122.146:31616`；
   这正是当初做 3002 代理的原因。用 tab 打开**直连地址**在远程场景必然失败；
2. **失去上下文**：用户在控制台里做了什么，PolyMind 不知道；回来要重新探测状态；
3. **仍可能需要代理**：若 tab 指向 `http://<polymind-host>:3002`，代理还在，只是不再需要剥 frame 头；
   但 Cookie Secure/Origin 仍需处理，复杂度不会归零。

结论：适合作为“控制台入口”的形态（launchpad + 新 tab），不适合作为唯一形态，除非确认所有用户都能直连节点。

### 方案 C（推荐）：单内嵌管理控制台 + 上下文入口 + 真实状态

1. **保留 30010 的 iframe**（已跑通，继续用）；
2. 在 ready 态把第 2/3 步从“人工勾选”改成**后端探测的真实状态**：
   - 第 2 步：业务集群是否存在、是否 Healthy（读管理 k3s 的 `BKECluster`）；
   - 第 3 步：目标 release 是否 `deployed`、Pod 是否 Ready（读业务集群）；
3. 每一步给一个**上下文按钮**：
   - 第 2 步 → “打开管理控制台”（现有 iframe 内滚动/聚焦，或新 tab）；
   - 第 3 步 → 集群存在时显示“打开业务控制台”（新 tab，优先走代理地址），否则显示“创建集群后可用”；
4. **不内嵌业务控制台**。31616 作为“高级操作/逃生舱”，而不是主路径；
5. 阶段 2/3 自动化落地后，主路径变成面板里的向导，控制台入口进一步降级。

这是改动最小、最符合“控制台是外部产品、PolyMind 是编排层”这一定位的方案。

### 方案 D：单 iframe + 控制台切换器（如果一定要在面板里看两个）

- 一个 iframe，头部下拉切换 `管理 / 业务`，src 在 3002/3003 之间切；
- 比双 iframe 省空间，但仍需要第二套代理、双登录、业务控制台生命周期处理；
- 切换会重新加载 SPA，登录态虽可共存但上下文丢失；
- 估算 1.5–2 天，之后每次 openFuyao 升级都要回归两套代理。

结论：仅在“必须面板内查看业务控制台”的硬需求下才做。

---

## 3. 推荐落地（最小改动）

### 3.1 后端

在现有 environment 响应上增加一个字段，不新建领域模型：

```json
{
  "business_console": {
    "available": true,
    "url": "https://192.168.122.146:31616",
    "proxy_url": "http://192.168.122.146:3003",
    "reason": null
  }
}
```

- `url`：业务集群 console 的 ingress 地址，优先从集群 Service/Ingress 发现；
  首版可用配置 `OPENFUYAO_BUSINESS_CONSOLE_PORT`（默认 31616）+ 环境 host 拼出；
- `available`：探测 `/rest/auth/login` 返回 200/302/303；
- `reason`：不可用时给“集群未创建/控制台未就绪”。

暂不做“控制台抽象层”，一个字段够用；等阶段 2/3 自动化落地后再收敛成 `consoles[]`。

### 3.2 前端

- `QuickStartChecklist` 第 2/3 步改为真实状态（读 `business_console.available` + 后续 cluster/app API）；
- 第 3 步按钮：可用 → `window.open(proxy_url ?? url)`；不可用 → 禁用 + 提示；
- 保留现有“打开控制台”（管理）按钮；
- 不做第二个 iframe。

### 3.3 验证 30010 是否能直接进业务集群（决定是否还需要 31616）

有业务集群后（阶段 2 完成）：

1. 登录 30010，进入集群列表，点 `bke-cluster`；
2. 观察浏览器地址是否变为 `/clusters/bke-cluster/...`、左侧是否出现“应用市场/应用管理”；
3. 若出现 → 31616 可完全降级为“直连入口”，PolyMind 只保留 30010 内嵌 + “在控制台打开”；
4. 若点击后跳到 `https://<host>:31616` 新 tab → 说明管理控制台本身就把业务控制台外链化，
   PolyMind 跟随同样做法即可（方案 C），不要自己再造一套内嵌。

---

## 4. 不推荐的做法

- **通用“任意网页都开 tab/都内嵌”的抽象**：只有两个固定控制台，做通用层是过度设计；
- **双 iframe 常驻**：空间、双登录、双代理维护都不划算；
- **在前端硬编码 31616**：端口来自部署，应该由后端发现/配置；
- **继续用 localStorage 人工勾选冒充阶段 2/3 状态**：这是当前体验最差的部分，比“少一个 iframe”更值得先修。

---

## 5. 优先级建议

| 优先级 | 事项 | 工作量 |
| --- | --- | --- |
| P0 | 第 2/3 步改为真实状态（先做可用性探测，再接自动化状态） | 0.5–1 天 |
| P0 | 业务控制台入口（新 tab，条件显示） | 0.5 天 |
| P1 | 阶段 2/3 自动化（上一轮方案） | 8–12 天 |
| P2 | 若确认 30010 不能进业务集群，再评估控制台切换器 | 1.5–2 天 |
| 不做 | 双 iframe、通用网页 tab 抽象 | — |

---

## 6. 待验证 / 待确认

1. 管理控制台 30010 选中集群后，是否直接加载该集群的应用市场插件（决定 31616 的定位）；
2. PolyMind 的用户是否都能直连节点：能 → 新 tab 直连即可；不能 → tab 必须走代理端口；
3. 业务控制台 URL 是否固定 31616，还是随 ingress 配置变化（决定发现逻辑）。
