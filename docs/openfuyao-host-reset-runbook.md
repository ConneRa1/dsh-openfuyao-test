# openFuyao 宿主机回退 Runbook

> 适用：当前 KVM 虚拟机 `auto_depoly`（openEuler 26.09，4C/8.6G），已通过 `bke init` 部署引导集群与 openFuyao 控制台。
> 目标：把 openFuyao/BKE 相关组件回退到“未部署”状态，保留 PolyMind 的代码、数据库和工作区。
> 风险：`bke reset --all --mount` 是破坏性操作，会清理容器运行时、网络、NTP、BKE 配置等；**优先使用虚拟机快照回退**。

---

## 0. 结论

**可以回退。** openFuyao 官方支持：

```bash
bke reset --all --mount
# 跳过确认：
bke reset --all --mount --confirm
```

官方删除范围：

| 命令/步骤 | 删除内容 |
| --- | --- |
| `bke reset`（含于 `--all`） | 本地 Kubernetes/k3s 过渡集群相关容器与目录 |
| `--all` | 容器服务、NTP、容器运行时、网络及相关残留 |
| `--mount` | 解压/挂载目录；与 `--all` 同用时处理 BKE 管理配置、时区等 |
| `rm -rf /bke`（可选） | BKE 安装/解压工作目录 |
| `rm -f /usr/local/bin/bke`（可选） | `bke` 命令 |

不会自动处理：网卡上的 VIP（当前环境未使用）。

---

## 1. 回退前必须做的事

### 1.1 虚拟机快照（强烈推荐）

当前是 KVM 虚拟机，优先在宿主机/虚拟化平台做快照：

```text
快照名：pre-openfuyao-reset-20261019
```

快照是本 Runbook 的首选回退路径。若 `bke reset` 后网络/NTP/容器运行时异常，直接回滚快照，比手工修复可靠。

### 1.2 停止 PolyMind 写入

```bash
# 先停前端/后端，避免 reset 期间网络/运行时变化导致写坏
bash /root/polymind/start.sh --stop 2>/dev/null || true
# 如通过其他方式启动，按实际进程停止：
# pkill -f 'next dev' ; pkill -f 'uvicorn src.witty_service.main'
```

### 1.3 备份 PolyMind 数据

```bash
mkdir -p /root/backup-20261019
cp -a /root/.witty/db /root/backup-20261019/ 2>/dev/null || true
cp -a /root/.witty/agent-workspaces /root/backup-20261019/ 2>/dev/null || true
cp -a /root/.polymind /root/backup-20261019/ 2>/dev/null || true
cp -a /root/witty-service/.env /root/backup-20261019/witty-service.env 2>/dev/null || true
cp -a /root/polymind/.env /root/backup-20261019/polymind.env 2>/dev/null || true
```

### 1.4 记录回退前状态

```bash
mkdir -p /root/openfuyao-reset-evidence
date > /root/openfuyao-reset-evidence/before.txt

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl get nodes -o wide >> /root/openfuyao-reset-evidence/before.txt 2>&1 || true
kubectl get pods -A >> /root/openfuyao-reset-evidence/before.txt 2>&1 || true
kubectl get bkeclusters -A >> /root/openfuyao-reset-evidence/before.txt 2>&1 || true
bke cluster list >> /root/openfuyao-reset-evidence/before.txt 2>&1 || true

systemctl list-units --type=service --all | grep -Ei 'k3s|containerd|bke|openfuyao' >> /root/openfuyao-reset-evidence/before.txt 2>&1 || true
ss -lntp >> /root/openfuyao-reset-evidence/before.txt 2>&1 || true
ps -ef | grep -E 'k3s|containerd|bkeagent' | grep -v grep >> /root/openfuyao-reset-evidence/before.txt 2>&1 || true
```

### 1.5 确认没有需要保留的业务集群

`bke reset --all` 会让当前引导节点上的业务/管理集群失去统一卸载入口。当前环境的 `bke-cluster` 状态为 `Checking`，没有健康的业务集群；如果后续在控制台创建过业务集群，先按官方文档删除业务集群，再重置引导节点。

---

## 2. 回退步骤

### 2.1 执行官方重置

```bash
# 建议先不带 --confirm，阅读提示后再确认
bke reset --all --mount
```

确认后：

```bash
bke reset --all --mount --confirm
```

如果 `bke` 提示找不到 kubeconfig，可显式指定：

```bash
bke reset --all --mount --confirm --kubeconfig /etc/rancher/k3s/k3s.yaml
```

### 2.2 删除 BKE 安装介质与命令（可选）

```bash
rm -rf /bke
rm -f /usr/local/bin/bke
```

如果后续还要在这台机器上验证，可以保留 `/bke` 和 `bke`，下次直接 `bke init`；但为了“干净机器”验证，建议删除。

### 2.3 清理残留（按需）

先查看，再删除；不要直接盲删：

```bash
ls -ld /bke /usr/local/bin/bke /etc/openFuyao /opt/openFuyao \
       /var/lib/bke /var/lib/openFuyao /var/log/openfuyao \
       /root/.openfuyao /var/lib/rancher /etc/rancher 2>/dev/null
```

确认后清理：

```bash
rm -rf /bke
rm -f /usr/local/bin/bke
rm -rf /etc/openFuyao
rm -rf /opt/openFuyao
rm -rf /var/lib/bke
rm -rf /var/lib/openFuyao
rm -rf /var/log/openfuyao
rm -rf /root/.openfuyao          # 含部署快照/临时口令，属于敏感残留
rm -rf /var/lib/rancher
rm -rf /etc/rancher
rm -rf /run/containerd
rm -f /root/.kube/config         # 先确认没有其他集群 kubeconfig
```

> `/root/.openfuyao` 里可能有部署快照和临时 root 口令文件，必须清理并轮换相关口令。
> `bke reset --all` 不一定会删除 `/opt/openFuyao`、`/var/lib/openFuyao`、`/var/lib/bke`、`/bke`，需要按上面的清单手工确认。

### 2.4 清理 BKE 写入的 `/etc/hosts`

BKE 会在 `/etc/hosts` 追加管理面域名/别名，例如：

```text
192.168.122.146 m1
192.168.122.146 default
192.168.122.146 http.bocloud.k8s
```

这些不是 openEuler 默认内容，回退时应删除；先备份：

```bash
cp -a /etc/hosts /root/hosts.before-openfuyao-cleanup
```

只删除 BKE 追加的行，保留 loopback 和原有主机记录；不要整文件覆盖。

### 2.5 检查网络/NTP/时区

`--all` 会清理网络、NTP、时区相关配置，回退后检查：

```bash
ip -4 addr show
ip route
cat /etc/resolv.conf
timedatectl
systemctl status chronyd --no-pager 2>/dev/null | head
```

如果网络/DNS/NTP 异常，优先回滚虚拟机快照；其次按 openEuler 原有配置恢复。

> 实测：`bke reset --all --mount --confirm` 在这一版 BKE 上会反复输出
> `RemovePodSandbox ... DeadlineExceeded` 警告，但最终 `BKE reset completed` 且退出码 0；
> 这些警告是清理 containerd pod 时的超时回退，不代表 reset 失败，仍应以“进程/端口/目录”验证为准。

---

## 3. 回退后验证

```bash
# 1. 进程/服务应不存在
ps -ef | grep -E 'k3s|containerd|bkeagent' | grep -v grep
systemctl list-units --type=service --all | grep -Ei 'k3s|containerd|bke|openfuyao'

# 2. 端口应关闭
ss -lntp | grep -E ':30010|:6443|:58080' || echo "openFuyao ports closed"

# 3. 命令/目录应不存在（若执行了可选清理）
which bke || echo "bke removed"
ls /bke 2>/dev/null || echo "/bke removed"

# 4. kubeconfig 不应再指向旧集群
kubectl get nodes 2>&1 | head
```

预期：

- 无 `k3s` / `bkeagent` / openFuyao 容器；
- 30010/6443/58080 不再监听；
- `bke`/`/bke` 已删除（如果执行了可选步骤）；
- PolyMind 可正常启动，聊天/数据库不受影响。

---

## 4. 恢复 PolyMind

```bash
# 按实际启动方式
cd /root/witty-service && nohup .venv/bin/uvicorn src.witty_service.main:create_app --factory --host 0.0.0.0 --port 8000 >/tmp/witty.log 2>&1 &
cd /root/polymind && nohup pnpm dev >/tmp/polymind.log 2>&1 &
```

验证：

```bash
curl -s http://127.0.0.1:8000/healthz
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

如果 PolyMind 启动失败，检查：

- `/etc/resolv.conf` / 网络是否被 reset 改动；
- Python/Node 依赖是否仍在；
- 数据库/工作区备份是否完整。

---

## 5. 回退失败时

| 现象 | 处理 |
| --- | --- |
| `bke reset` 报 kubeconfig 错误 | 指定 `--kubeconfig /etc/rancher/k3s/k3s.yaml`；或先修复 kubeconfig |
| reset 后网络/DNS 异常 | 回滚虚拟机快照；检查 `/etc/resolv.conf`、NetworkManager |
| `containerd` 被删除但其他服务依赖 | 重新安装 containerd；或回滚快照 |
| 30010/6443 仍监听 | 检查残留进程/容器；`bke reset --all --mount` 重跑 |
| PolyMind 起不来 | 回滚快照；检查数据库/工作区备份 |

---

## 6. 建议的后续顺序

1. 在 KVM 宿主机给当前 VM 做快照；
2. 增加 vCPU/内存到 8C/16G（按虚拟化平台要求关机/重启）；
3. 按本 Runbook 回退 openFuyao；
4. 在干净状态重新验证；
5. 另起一台干净机器做最终验收（不要复用这台已装过 BKE 的机器）。
