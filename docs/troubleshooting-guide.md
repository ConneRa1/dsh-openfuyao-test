# PolyMind / witty-service 排障手册

> 面向：刚接手这套系统、还不熟悉"请求会经过哪些程序"的同学。
> 目标：看到任何异常（500、502、白屏、Agent 不动、部署卡住）都能自己定位到**具体哪一层、哪个文件、哪一行**。
> 本机（openEuler 26.09，`auto_depoly`）上的路径与端口都以实际部署为准。

---

## 0. 先记住一张图：一个请求会经过谁

```
浏览器
  │  http://192.168.122.146:3000
  ▼
nginx :3000  ── /api/*  ──────────────►  后端 FastAPI :8000
  │                                        │
  │  /*  （页面、静态资源）                 ├─ 启动 Agent 沙箱进程 :随机端口（uvicorn witty_agent_server）
  ▼                                        │      └─ 调模型 API、执行 witty-service CLI、bke
Next.js :3001                              │
                                           └─ SQLite /var/lib/witty-service/.witty/db/witty_service.sqlite3

右面板 iframe ──► nginx :3002 ──► https://127.0.0.1:30010 （openFuyao 控制台）
```

四个直接推论，先建立直觉：

1. **页面打不开 / 白屏** → 大概率是 Next(`:3001`) 或 nginx(`:3000`)，跟后端无关。
2. **页面能开、但操作报错（弹 500/409）** → 后端(`:8000`) 的问题，去 `journalctl`。
3. **后端没报错、但 Agent 不动或胡说** → Agent 沙箱进程（随机端口）或模型配置。
4. **右侧面板一直是"未部署"或 502** → openFuyao 控制台(`:30010`) 或 nginx `:3002`。

**排查的第一件事永远是：决定去哪个日志看。** 走错楼层会浪费一小时。

---

## 1. 万能三步法

### 第一步：在浏览器里看清"到底什么错了"

按 `F12` → `Network` 面板 → 重新触发一次操作 → 点那条红色请求：

| 看什么 | 说明 |
| --- | --- |
| **Status Code** | 500=后端崩了，502=后端/网关没起来，504=超时，409=状态冲突，404=路径或对象不存在 |
| **Response** | FastAPI 的 500 常常**没有 JSON**，只有一行 `Internal Server Error`；而 4xx 一般有 `{"error":{"code":"...","message":"..."}}` |
| **Preview/Response 里的 `error.code`** | 这是最值钱的线索，直接拿去 `grep` 代码 |

> 如果响应体里带 `code`，说明是**业务错误**，代码是主动抛的，`grep` 这个 code 就能找到位置。
> 如果只有 `Internal Server Error`，说明是**未捕获异常**，必须看后端日志。

### 第二步：看后端日志里的 traceback

```bash
# 实时跟（复现操作时开着这个窗口）
journalctl -u witty-backend -f

# 看最近 5 分钟
journalctl -u witty-backend --since "5 min ago" --no-pager

# 只要错误
journalctl -u witty-backend --since "30 min ago" --no-pager | grep -n "ERROR\|Traceback\|Error:"
```

### 第三步：如果和 Agent 行为有关，再看沙箱

```bash
# 每个 Agent 一个目录
ls /var/lib/witty-service/.witty/agent-workspaces/
cat /var/lib/witty-service/.witty/agent-workspaces/<agent_id>/workspace/agent-server.stderr.log

# 或者用接口看 openFuyao 部署过程的完整日志
curl -s -H "Authorization: Bearer $AUTH_TOKEN" \
  http://127.0.0.1:8000/openfuyao/environments/<env_id>/logs
```

---

## 2. 五个"一眼看健康"的命令

出问题先跑这五条，30 秒内就能知道哪层挂了。

```bash
# 1) 后端服务状态（active 才正常）
systemctl status witty-backend --no-pager

# 2) 后端活着吗
curl -s http://127.0.0.1:8000/healthz          # 期望 {"status":"ok"}

# 3) 端口都在听吗（8000 后端 / 3001 Next / 3000&3002 nginx）
ss -lntp | grep -E ':(8000|3001|3000|3002)\b'

# 4) 前端健康
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/health   # 期望 200

# 5) Agent 进程还在吗（进程数和 /agents 里的 running 数量对得上）
ps -ef | grep witty_agent_server | grep -v grep
```

### 顺手记住的端口表

| 端口 | 谁 | 备注 |
| --- | --- | --- |
| 3000 | nginx（对外入口） | `/api/*` 转发到 8000，其余转发到 3001 |
| 3001 | Next.js | 只监听本机，页面渲染 |
| 3002 | nginx（控制台网关） | 反代到 `https://127.0.0.1:30010`，并剥掉 `X-Frame-Options` |
| 8000 | 后端 FastAPI | 只监听 `127.0.0.1` |
| 30010 | openFuyao 控制台 | BKE 部署后才存在 |
| 随机 | Agent 沙箱 | `GET /agents` 返回的 `process_port` |

---

## 3. 用 curl 直接问后端（绕过前端，排除干扰）

排查时最有效的一招：**绕过前端，直接打后端**。如果 curl 成功、页面失败，问题就在 nginx/Next/浏览器；如果 curl 也失败，问题就在后端。

```bash
# 把 token 读进环境变量（backend 的鉴权 token 在这里）
set -a; . /etc/witty-service/witty-service.env; set +a

# 验证 token 有效
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $AUTH_TOKEN" \
  http://127.0.0.1:8000/agents

# 查所有接口（排障时的"地图"）
curl -s http://127.0.0.1:8000/openapi.json | python3 -c "
import json,sys
for p,ops in sorted(json.load(sys.stdin)['paths'].items()):
    print(','.join(m.upper() for m in ops).ljust(22), p)"
```

`401` 就是 token 不对；`200` 说明后端和鉴权都正常，问题在更前面或更后面。

---

## 4. 直接查数据库（确认"数据到底有没有写进去"）

```bash
DB=/var/lib/witty-service/.witty/db/witty_service.sqlite3

sqlite3 -header -column $DB "select id,name,provider,enabled,is_default from models;"
sqlite3 -header -column $DB "select id,name,status,model_id from agents;"
sqlite3 -header -column $DB "select id,agent_id,status,phase,progress,console_url from openfuyao_environments;"
```

三条纪律：

1. **只读查询随便用**，`update/delete` 前先 `cp` 一份备份。
2. 表结构不清楚就先 `.schema agents`。
3. 数据库和服务器的**认知差**往往是 bug 根源：页面说成功了但表里没有 → 事务回滚了；表里有但页面没有 → 缓存或查询条件问题。

---

## 5. 症状 → 最可能的原因（速查表）

| 现象 | 最可能原因 | 第一步去看 |
| --- | --- | --- |
| 页面 500，响应体只有 `Internal Server Error` | 后端未捕获异常 | `journalctl -u witty-backend` 的 traceback |
| 页面 500，响应体有 `error.code` | 业务规则拦截（权限、状态机） | `grep` 这个 code |
| 502 Bad Gateway | 上游没起来或崩了 | `ss -lntp`、`systemctl status` |
| 504 | 长任务超时（`bke init` 等） | nginx `proxy_read_timeout`、任务日志 |
| 409 `HOST_ALREADY_CLAIMED` | 同一台机器已有 openFuyao 环境 | `openfuyao_environments` 表 |
| 409 模板"已实例化" | 一模板一实例，之前建过 | `agents` 表里同名记录 |
| 404 `SESSION_NOT_FOUND` | session 要先创建再用 | `POST /agents/{id}/sessions` |
| 白屏、控制台有 JS 报错 | Next 构建产物与后端地址不匹配 | 浏览器 Console；`NEXT_PUBLIC_*` 是否重新构建 |
| Agent 一直"思考中"或秒失败 | 模型不可用 / API Key 错 | Agent 的 `agent-server.stderr.log` |
| 右面板空白但 3002 能开 | iframe 被 `X-Frame-Options` 拦 | `curl -I http://127.0.0.1:3002/` |
| iframe 里显示「某 IP 响应时间过长」 | 浏览器连不上该 IP（NAT/端口转发），不是后端超时 | 见 7.7；先用浏览器直开代理地址 |
| 右侧"未部署"但集群其实好了 | 环境状态没刷新 | `openfuyao_environments` 的 `status/phase` |

---

## 6. 案例复盘：初始化 Agent 模板报 500（Permission denied）

这次的真实故障，完整走一遍，**重点看"怎么读 traceback"**。

### 6.1 现象

在"智能体 → 模板 → 初始化"点确认，页面报 500。

### 6.2 定位

```bash
journalctl -u witty-backend -n 200 --no-pager | grep -A5 "ERROR"
```

日志里有三段 traceback，关键几行是：

```
FileNotFoundError: [Errno 2] No such file or directory:
    '.../agent-workspaces/9bcc82e0-.../workspace/.agent'
During handling of the above exception, another exception occurred:
...
PermissionError: [Errno 13] Permission denied:
    '/var/lib/witty-service/.witty/agent-workspaces/9bcc82e0-...'
```

### 6.3 怎么读这段 traceback（这是本节的重点）

Python 的 traceback 是**从外到内**打印的：**最后一行才是最终抛出的错误**。所以：

1. **先看最后一行**：`PermissionError: [Errno 13] Permission denied` + 路径。这就是真凶——**权限**，不是"文件不存在"。
2. **再看应用代码帧**：从下往上找第一个属于本项目的文件，就是"代码走到哪一步炸的"：
   ```
   src/witty_service/storage/workspace_store.py:40  in init_workspace
   src/witty_service/application/agent_manager.py:813 in create_agent
   src/witty_service/api/agent_templates.py:85 in instantiate_agent_template
   ```
   一条清晰的调用链：API → 创建 Agent → 初始化工作目录。
3. **再看 `During handling of the above exception`**：它说明后面的异常是"处理前一个异常时又炸了"。前面的 `FileNotFoundError` 只是 `pathlib` 在**逐级创建父目录**时的中间状态：父目录不存在 → 尝试创建父目录 → 到最顶层时发现**没写权限** → 抛 `PermissionError`。

> **经验**：`mkdir(parents=True)` 这类库调用最容易制造这种"假线索"。判断方法很简单——**errno 是 13 就是权限，是 2 才是路径不存在**。以最后一个异常为准。

### 6.4 根因

```bash
ls -ld /var/lib/witty-service/.witty/agent-workspaces
# drwxr-xr-x. root root ...  ← 目录属于 root
id witty-service               # 后端以 witty-service 身份运行
```

后端以 `witty-service` 用户运行，而这个目录是 **root** 创建的（之前用 root 跑过 CLI / 手工建过 Agent）。`witty-service` 在这个目录下**没有写权限**，所以无法创建 `agent-workspaces/<uuid>/workspace`。

一句话：**服务用户写不进 root 建的目录**。这是"环境状态"问题，不是代码 bug。

### 6.5 修复

```bash
# 立即修复：把属主改回服务用户
chown -R witty-service:witty-service /var/lib/witty-service/.witty/agent-workspaces

# 永久预防：systemd 启动时自动校正（drop-in 已加，见下）
cat /etc/systemd/system/witty-backend.service.d/workspace-perms.conf
```

`workspace-perms.conf` 的内容：

```ini
[Service]
ExecStartPre=+/usr/bin/install -d -o witty-service -g witty-service -m 0755 \
    /var/lib/witty-service/.witty/agent-workspaces
```

`+` 前缀 = 以 root 执行（忽略 `User=`），`install -d` 对**已存在**的目录也会重设属主/权限。

> 为什么需要它：systemd 的 `StateDirectory=` 只保证 `/var/lib/witty-service` 本身属于服务用户，**不管子目录**。只要有人用 root 先创建了子目录，下一个人就会踩这个坑。

### 6.6 验证（必须做到这一步才算修完）

```bash
set -a; . /etc/witty-service/witty-service.env; set +a

# 通过前端入口（:3000 → nginx → backend，走你点按钮时的同一条路）
curl -s -o /tmp/r.json -w "%{http_code}\n" -X POST \
  -H "Authorization: Bearer $AUTH_TOKEN" -H "Content-Type: application/json" \
  -d '{"model_id":"<model_id>","sandbox_type":"local_process"}' \
  http://127.0.0.1:3000/api/agent-templates/openfuyao-deployer/instantiate
# 期望 201，且返回体里有 id / workspace_path / process_port
```

**验证要点**：一定要走**用户实际走的那条链路**（这里是 `:3000`），而不是只打 `:8000`。这样才同时验证了 nginx 转发、鉴权、后端逻辑。

---

## 7. 六个真实踩过的坑（每个都值得记住）

### 7.1 改了代码但没生效：两处副本

这台机器上源码和运行副本是**两份**：

| 位置 | 谁在用 |
| --- | --- |
| `/opt/witty-service/src` | systemd 后端（`PYTHONPATH` 指向它） |
| `.venv/.../site-packages/witty_service` | `witty-service` 命令行 |

```bash
# 改完代码后的同步（从仓库目录执行）
cp -a /root/witty-service/src/witty_service/. /opt/witty-service/src/witty_service/
cp -a /root/witty-service/src/witty_service/. \
  /opt/witty-service/.venv/lib/python3.12/site-packages/witty_service/
systemctl restart witty-backend
```

判断"是不是没同步"：日志里的**行号对不上**，或报错指向一段你已经删掉的代码。

### 7.2 前端环境变量是"编译期"注入的

`NEXT_PUBLIC_*` 在 `next build` 时就被**写死**进产物。改 `.env` 后**必须重新构建**，`restart` 无效。

```bash
cd /root/polymind
NEXT_PUBLIC_AGENTD_API_URL=/api NEXT_PUBLIC_WS_URL=/api/ws NEXT_PUBLIC_AUTH_TOKEN=<token> \
  npm run build
```

### 7.3 SELinux 拦截 systemd 读 `/root` 下的文件

现象：`systemctl status` 报 `203/EXEC` 或 `Permission denied`，但手工执行完全正常。
原因：SELinux（`getenforce` 为 `Enforcing`）不允许服务读 `/root`。
现在前端和 nginx 是**手工进程**（不是 systemd 托管），所以**重启机器后会消失**，需要重跑：

```bash
nginx -c /root/.polymind/nginx/nginx.conf
setsid nohup /root/.nvm/versions/node/v24.22.0/bin/polymind \
  > /root/.polymind/frontend.log 2>&1 < /dev/null &
```

### 7.4 cgroup v2 让 BKE 起不来

现象：`bke init` 报 `failed to find cpu cgroup (v2)`。
检查：

```bash
stat -fc %T /sys/fs/cgroup     # 期望 tmpfs（cgroup v1）；cgroup2fs 就是 v2，BKE 会失败
grep cgroup /proc/cmdline      # 应有 systemd.unified_cgroup_hierarchy=0
```

### 7.5 端口占用导致预检失败

```bash
ss -lntp | grep -E ':(80|443|6443)\b'
```

预检会检查 80/443 是否被占。注意：**以非 root 运行的后端看到的现象可能不准**，所以预检改为读 `/proc/net/tcp`，并以 `sudo -n` 提权执行 `bke`。

### 7.6 `sudo -n` 与 sudoers

后端以 `witty-service` 身份跑，但要执行 `bke`/`kubectl`。免密规则在：

```bash
cat /etc/sudoers.d/90-witty-openfuyao
# 验证（不输出密码提示即为通过）
sudo -u witty-service sudo -n -l /usr/local/bin/bke >/dev/null && echo ok
```

### 7.7 端口转发（VS Code SSH）下控制台 iframe 打不开

**现象**：右侧面板里显示「192.168.122.146 的响应时间过长」，但集群是好的、直接
在虚拟机里访问 `:30010` 又正常。

**这是浏览器报的错，不是后端**。Chrome 在 iframe 里等待连接超时，会渲染自己的错误页
（`ERR_CONNECTION_TIMED_OUT`），所以页面上看到的是一行地址加"响应时间过长"。

**原因**：iframe 以前直接使用后端记录的内网地址 `http://192.168.122.146:3002/`。
而你是用 VS Code 端口转发访问前端的，浏览器只知道 `localhost:3000`，
**路由不到虚拟机的内网段** `192.168.122.x`，于是一直等到超时。

**修复**：`resolveProxyUrl`（`lib/openfuyao-console.ts`）改为**跟随浏览器实际访问的
host**，只沿用后端给的端口。现在 iframe 地址 = 你访问页面用的地址 + `:3002`。

**用法变化**：需要把 **3002** 也转发出来：

1. VS Code → `PORTS` 面板 → `Forward a Port` → 填 `3002`；
2. 浏览器访问 `http://localhost:3000`，面板 iframe 就是 `http://localhost:3002/`。

如果本来就是用局域网 IP（`http://192.168.122.146:3000`）访问，则和以前完全一样，
不需要额外设置——因为页面 host 本身就是可达地址。

**自检：先验证链路，再怀疑代码。**

```bash
# 在虚拟机里确认网关本身是好的
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3002/   # 303/200 都正常
```

然后在**你自己的浏览器**里先直接打开 `http://localhost:3002`：看到 openFuyao 登录页，
说明转发通了，再回面板；如果这里都打不开，就是转发没配好，与前端代码无关。

**通用经验**：凡是"后端返回绝对地址给前端 iframe/跳转用"的设计，在 NAT、端口转发、
反向代理后面都会失效。判据是：**这个地址是给浏览器用的，还是给服务器用的？**
给浏览器用的地址必须由浏览器自己推导（`window.location`），不能由服务端写死。

### 7.8 控制台登录报「您的登录cookie已经过期」

**这不是密码错误，也不是网络问题。** 它是控制台登录接口的**同源校验**失败，
提示语有误导性。

**最实用的判据：看失败次数有没有递减。**

```bash
kubectl get user admin -o jsonpath='{.status}'     # {"RemainAttempts":5,...}
```

登录一次后再看：

- 次数**减少** → 请求真的进了密码校验，报错可信；
- 次数**不变** → 请求在校验密码之前就被拒了，提示与密码无关，别再换密码试。

**根因**：控制台要求 `Origin == https://<Host 含端口>`。网关对外是 http，
且 `proxy_set_header Host $host` 会丢掉端口，于是每次登录都在会话阶段被拒。

**修法**（nginx 控制台网关）：

```nginx
proxy_set_header Host $http_host;                 # 必须带端口
proxy_set_header Origin "https://$http_host";     # 上游只认 https 源
proxy_set_header Referer "https://$http_host$request_uri";
```

**验证**：修好后错误提示会变成「用户名或密码错误，再输错 N 次用户将锁定」——
说明链路终于走到了凭据校验。

> 通用教训：**报错文案不可信，用「副作用是否发生」判断真实阶段**。
> 这里的副作用就是失败计数；计数器不动，就说明服务器压根没验密码。

---

## 8. 改完代码后的验证闭环

按顺序做完，才算"真的好了"：

```bash
cd /root/witty-service

# 1) 单元测试（快，先跑相关模块）
.venv/bin/python -m pytest tests/unit/test_openfuyao_preflight.py -q
# 全量（约 1800 条，慢）
.venv/bin/python -m pytest -q

# 2) 静态检查
.venv/bin/ruff check src tests

# 3) 同步到运行副本 + 重启
cp -a src/witty_service/. /opt/witty-service/src/witty_service/
systemctl restart witty-backend && sleep 2 && curl -s http://127.0.0.1:8000/healthz

# 4) 用"用户路径"复现一次（curl 或浏览器）
```

---

## 9. 排查纪律（比技巧更重要）

1. **先复现，再动手。** 不能稳定复现的问题，先加日志让它可复现。
2. **一次只改一个变量。** 同时改三处，修好了也不知道是哪处。
3. **相信第一现场。** 日志里的 traceback 比你的猜测可靠；不要因为"我觉得应该是 X"就跳过看日志。
4. **先分清"代码 bug"和"环境状态"。**
   - 代码 bug：同样的输入在哪台机器都错 → 读代码、写测试。
   - 环境状态：别人机器好的、你这台错；errno 是 13/2、端口占用、配置缺失 → 查环境。
   - 本次 500 属于后者。
5. **从最外层往里二分。** 用 curl 绕过前端；再绕过 nginx 直连 8000；再绕过接口直查数据库。每绕一层，范围就小一半。
6. **修完立刻写下来。** 写进 `docs/`，下次（包括三个月后的你）能省一小时。

---

## 10. 一页速查

```bash
# 服务
systemctl status witty-backend --no-pager
journalctl -u witty-backend -f
systemctl restart witty-backend

# 健康
curl -s http://127.0.0.1:8000/healthz
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/health

# 端口 / 进程
ss -lntp | grep -E ':(8000|3001|3000|3002|30010)\b'
ps -ef | grep witty_agent_server | grep -v grep

# 鉴权
set -a; . /etc/witty-service/witty-service.env; set +a
curl -s -H "Authorization: Bearer $AUTH_TOKEN" http://127.0.0.1:8000/agents

# 数据库
sqlite3 -header -column /var/lib/witty-service/.witty/db/witty_service.sqlite3 \
  "select id,name,status,model_id from agents;"

# Agent 日志
ls /var/lib/witty-service/.witty/agent-workspaces/
tail -f /var/lib/witty-service/.witty/agent-workspaces/<id>/workspace/agent-server.stderr.log

# 前端 / 网关日志
tail -f /root/.polymind/frontend.log
tail -f /root/.polymind/nginx/error.log
```
