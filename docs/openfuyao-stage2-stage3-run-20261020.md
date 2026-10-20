# openFuyao 阶段 2/3 实跑报告（2026-10-20）

## 结论

- **阶段 2：业务集群已创建并健康**。BKE 状态 `ClusterReady / Healthy / Ready`，节点 `auto-depoly` 为 `Ready`，控制面、calico、coredns、ingress、harbor、console、marketplace、application-management 等 Pod 全部 Running/Completed。
- **阶段 3：应用已通过应用市场链路安装并验证**。`nginx-demo`（Bitnami nginx chart 25.2.5，appVersion 1.31.7）在 `default` 命名空间 `deployed`，Pod `1/1 Running`，NodePort `32424` 返回 `HTTP 200` 和 “Welcome to nginx!”。
- 应用管理 API `GET /rest/application-management/v1beta1/helm-releases` 已能看到 `nginx-demo`（status=deployed，description=Upgrade complete）。

## 关键过程与修复

### 1. 预检

最终预检：46 项适用，**44 通过、2 失败**，失败仅为：

- 节点发行版 openEuler 26.09 不在 BKE 策略矩阵（20.03/22.03/24.03/Ubuntu 22.04/UOS 20 1070e）；
- 内核 `6.6.0-175.0.0.5.oe2609.aarch64` 不在兼容矩阵。

这两项按项目文档记录为“26.09/6.6.x 已知矩阵例外”（同机 `bke init` 已成功），继续执行。其余端口、CPU、磁盘、Chart/安装源/镜像仓库、root/免密 sudo、管理集群 API 等全部通过。

内存从 14.5 GiB 扩到 **18.39 GiB（VM 配置 20G）** 后，预检内存项通过。

### 2. 第一次创建失败与清理

第一次 `bke cluster create` 卡在 `InitControlPlane`，6443 一直不监听。根因：

- 原主机名 `auto_depoly` 含下划线，Kubernetes 节点名不允许下划线；
- kubelet 拒绝加载 `etcd-auto_depoly`、`kube-apiserver-auto_depoly` 等静态 Pod，控制面无法启动。

处理：

- 停止卡住的 create，删除失败的 BKECluster/BKENode/Machine/Cluster 等 CR；
- 主机名改为合法的 `auto-depoly`，同步更新 `/etc/hosts` 和 nodes.yaml；
- 备份并移走失败集群的 `/etc/kubernetes` 与 `/var/lib/kubelet`；
- 停止残留 bkeagent，释放 58080；
- 恢复 `/root/.kube/config` 指向管理集群后重新预检并创建。

第二次创建成功；`/etc/kubernetes/manifests` 中静态 Pod 名变为 `etcd-auto-depoly`、`kube-apiserver-auto-depoly` 等，6443 正常监听。

### 3. 阶段 3 应用市场

- 业务控制台：`https://192.168.122.146:31616/`（ingress NodePort 31616）。
- 首次用默认 `admin/test@1234` 登录成功，按首次登录流程改为强口令；凭据保存在 `/root/.openfuyao/console-admin.cred`（600）。
- 应用市场仓库：
  - `openFuyao`（内置）；
  - `local`（业务集群 local-harbor chartmuseum）；
  - `bitnami`（已添加、已同步）。
- **重要限制**：Bitnami 新 chart 走 OCI `registry-1.docker.io/bitnamicharts`，本机到 Docker Hub 被墙，直接从未修改的 Bitnami 仓库安装会报 `error pulling OCI chart ... connection reset by peer`。
- 绕过方式：通过可达的 `docker.m.daocloud.io` 拉取 `bitnamicharts/nginx:25.2.5` chart，上传到 local-harbor chartmuseum，再从应用市场 `local` 仓库安装；镜像使用 `docker.m.daocloud.io/bitnami/nginx:latest`。
- Bitnami chart 需要 `global.security.allowInsecureImages=true` 才允许非官方 registry 镜像；首次用 `nginx:alpine` 会因 init 容器缺 `/bin/bash` 失败，改用 Bitnami nginx 镜像后正常。

## 当前状态

### 业务集群

| 项 | 值 |
| --- | --- |
| 集群名/命名空间 | `bke-cluster` / `bke-cluster` |
| BKE 状态 | `ClusterReady / Healthy / Ready` |
| API Endpoint | `https://192.168.122.146:6443` |
| 节点 | `auto-depoly`，`control-plane,master,node,worker`，`Ready` |
| Kubernetes | `v1.34.3-of.1` |
| 容器运行时 | containerd 2.1.1 |
| kubeconfig | `/etc/kubernetes/admin.conf`（业务集群）；`/etc/rancher/k3s/k3s.yaml`（管理集群） |
| `/root/.kube/config` | 当前指向业务集群（BKE 创建时写入） |

### 应用

| 项 | 值 |
| --- | --- |
| Release | `nginx-demo`（namespace `default`） |
| Chart | `nginx-25.2.5`（Bitnami，经 local 仓库） |
| 镜像 | `docker.m.daocloud.io/bitnami/nginx:latest` |
| Pod | `nginx-demo-6db7bcc9dd-vhf2h`，`1/1 Running` |
| Service | `nginx-demo`，NodePort `80:32424/TCP`、`443:31822/TCP` |
| 访问 | `http://192.168.122.146:32424/` → 200 “Welcome to nginx!” |
| 应用管理 API | 可见 `nginx-demo`，status `deployed` |

验证命令：

```bash
kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n bke-cluster get bkecluster,bkenode
kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes,pods -A
helm list -A --kubeconfig /etc/kubernetes/admin.conf
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.122.146:32424/
```

## 控制台与访问

| 入口 | 地址 | 凭据/说明 |
| --- | --- | --- |
| PolyMind Web | `http://192.168.122.146:3000/` | 无需登录（当前演示形态） |
| 管理控制台 | `https://192.168.122.146:30010/` | 登录密码是你之前改过的；我**没有重置**。不要再用默认 `test@1234` 尝试（会锁定，当前仅剩 4 次）。 |
| 业务控制台 | `https://192.168.122.146:31616/` | `admin` / 见 `/root/.openfuyao/console-admin.cred` |
| 业务 API | `https://192.168.122.146:6443` | 管理 kubeconfig：`/etc/kubernetes/admin.conf` |

管理控制台登录说明：我曾用默认 `admin/test@1234` 尝试一次，返回“用户名或密码错误，再输错 4 次用户将锁定”，说明密码已被修改；为避免锁号，未继续尝试、也未重置。管理控制台的集群列表按 BKE CR 展示，`bke-cluster` 已 `Healthy`，正常应能看到。

## 新增/变更的系统项

- 新增专用 SSH 部署用户 `bkedeploy`（UID 1001，NOPASSWD sudo），供 BKE 的 BKENode 密码认证使用：
  - 密码：`/root/.openfuyao/bkedeploy.cred`（600）
  - sudoers：`/etc/sudoers.d/91-bkedeploy`
  - 说明：BKENode 当前版本只支持用户名/密码，不支持 SSH key；这是按项目文档“专用部署用户 + 临时凭据”的降级方案。后续可改为正式凭据并删除该用户。
- 主机名：`auto_depoly` → `auto-depoly`（`/etc/hostname`、`/etc/hosts` 已更新）。
- 内存：VM 配置 20G，`MemTotal` 18.39 GiB。
- 备份：
  - 创建前快照：`/root/.openfuyao/pre-deploy-20261020-123432/`
  - 失败集群的 `/etc/kubernetes`：`/etc/kubernetes.failed-20261020-123925`
  - 失败集群的 `/var/lib/kubelet`：`/var/lib/kubelet.failed-20261020-123925`

## 已知限制

1. **Bitnami 仓库直装仍会失败**：其 chart 元数据在 HTTP index，但 chart 包走 OCI `registry-1.docker.io`，当前网络不可达。要恢复“Bitnami 仓库直接安装”，需要给 marketplace-service 配 Docker Hub 代理/镜像，或把 chart 同步到 local 仓库（本次做法）。
2. **OS/内核矩阵例外**：openEuler 26.09 + 6.6.0-175 不在 BKE 官方矩阵；本次按项目文档记录例外继续。升级 BKE 版本前建议复核。
3. **管理控制台密码未知**：你改过的密码我没有重置，也没有继续尝试。业务控制台是独立的新密码。
4. **同机 AIO**：管理 k3s、业务集群、PolyMind、控制台同机运行；内存 18.39 GiB、当前可用约 10 GiB。后续再加负载前先看 `free -h`。
5. **手工进程**：PolyMind Web/Nginx 仍是手工进程（重启机器后需重新拉起）；`witty-backend`、业务 `kubelet`、`bkeagent` 已由 systemd 管理。

## 回滚

```bash
# 删除业务集群 CR（会触发 BKE 清理；确认后再执行）
kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n bke-cluster delete bkecluster bke-cluster

# 卸载 nginx（保留集群）
helm uninstall nginx-demo -n default --kubeconfig /etc/kubernetes/admin.conf

# 删除专用部署用户（确认不再需要 BKE 密码认证后）
userdel -r bkedeploy
rm -f /etc/sudoers.d/91-bkedeploy
```

注意：不要用 `bke reset --all` 清理业务集群，它可能影响管理集群/控制台；优先删除 `bkecluster` CR。

## 关键日志

- 业务集群创建日志：`/var/log/openfuyao/cluster-create-20261020-123958.log`
- 预检报告：`/root/.openfuyao/cluster/preflight-retry2.txt`（44/46）
- 业务控制台 API 会话：`/tmp/biz-cj2.txt`（临时文件，重启后失效）

## 2026-10-20 14:22 事故与恢复（重要）

在评估后续自动化时误执行了 `bke reset --doc`：该子命令的 `--doc` 仍会执行 reset。默认 `bke reset` 只清理**本机 Kubernetes（管理 k3s）**，未带 `--all/--mount`：

- 管理 k3s（`/var/lib/rancher/k3s`、`/etc/rancher`、k3s 进程）被删除，管理控制台 30010、仓库端口 40080/40443/38080 停止；
- 业务集群未受影响：kubelet/apiserver 仍运行，`auto-depoly` Ready，`nginx-demo` Pod Running，`http://192.168.122.146:32424/` 仍为 200；
- 业务控制台 31616 仍可访问。

恢复过程：

1. 首次 `bke init` 因 NTP（`127.0.0.1:123 refused`）失败，改用 `--enableNTP=false`；
2. 第二次仍失败：`/root/.kube/config` 指向业务集群，console 被装到业务集群并因 Service CIDR（`100.10.0.10` vs `10.96.0.0/16`）不匹配报错；
3. 将 `/root/.kube/config` 备份为 `/root/.kube/config.business-20261020` 后重跑 `bke init`；
4. 14:27:57 输出 `BKE initialization is complete`，管理控制台恢复（`303 → 登录`），k3s 在 36443 端口。

恢复后的状态：

- 管理 k3s 是**全新的空集群**（v1.25.16+k3s4，API 36443），`bke-cluster` 的 BKECluster CR 已不存在，即业务集群仍在运行但管理面不再跟踪它；下一次全量 reset 会一并清理；
- 管理控制台数据随 k3s 重建，默认 `admin/test@1234` 恢复可用（首次登录会强制改密），之前改过的密码不再有效；
- `/root/.kube/config` 现指向管理 k3s（36443），供 `bke` 使用；业务 kubeconfig 备份在 `/root/.kube/config.business-20261020`，业务集群日常操作请显式用 `/etc/kubernetes/admin.conf`；
- 阶段 1 只读预检（`preflight-after-reset-20261020.txt`）当前仍失败：`宿主机清洁度`（业务集群残留）、`端口占用 6443`，符合“必须全量 reset 才能回归阶段 1”的判断。

经验：

1. `bke reset --doc` 不是只读命令，自动化里禁止对 reset 使用 `--doc`；
2. 重跑 `bke init` 前必须确保 `/root/.kube/config` 不指向其它集群，或显式传 `--kubeconfig`；
3. 业务 kubeconfig 备份：`/root/.kube/config.business-20261020`。
