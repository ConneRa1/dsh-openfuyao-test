# openFuyao 多节点 spike 结论（2026-10-20 晚）

> 目的：在动手写阶段 2 之前，用一次真实预检/创建回答三个卡设计的问题。
> 环境：本机 `auto-depoly` / 192.168.122.146（引导节点 + 管理 k3s 36443）；新虚机 `192.168.122.151`
> （openEuler 24.03 LTS-SP3，4C / 2.8 GiB / 44 GiB），root + 密码认证，SSH 22 端口直连可达。
> 产物目录：`/root/.openfuyao/multi-test/`（`preflight-baseline.json`、`create-hn.log`，均 0600）。

## 结论速览

| # | 问题 | 结论 |
| --- | --- | --- |
| 1 | `nodes.yaml` 多文档是否被接受、`--output json` 结构 | **接受**。单文件多文档，62 条检查跨 2 个节点 + 集群级；`--output json` 输出**单文档**结构化报告，**退出码 3** 表示预检失败 |
| 2 | `bke cluster scale` 是否可用 | **不可用**（未注册）。`--help` 与无参调用都落到父命令 `bke cluster` 的 help，退出码 0 |
| 3 | `spec.hostname` 与实际 hostname 不一致 | **既不报错也不改 OS hostname**：kubelet 用 `--hostname-override` 注册成 `spec.hostname` |

---

## Spike 1：多文档 + JSON 契约

`nodes.yaml` 用 `---` 分隔两个 `BKENode`，`cluster.yaml` 用 `bke-multi` 命名空间，执行：

```bash
bke preflight cluster-create -f cluster.yaml -n nodes.yaml --output json
# EXIT=3
```

**被接受**：`results` 里同时出现 `@bke-multi-m1`（master）与 `@bke-multi-n1`（worker）的实例，
另有 `@cluster` 级检查（拓扑、唯一性、管理集群、网络 CIDR 等）。

### 报告结构（稳定字段）

```json
{
  "schemaVersion": "v1",
  "operation": "cluster-create",
  "planHash": "sha256:…", "configDigest": "sha256:…", "bundleDigest": "sha256:…",
  "overall": "FAIL",              // PASS / FAIL / WARN?
  "exitCode": 3,                  // 与进程退出码一致
  "summary": {"total": 62, "pass": 57, "fail": 5, "warn": 0, "skip": 0},
  "results": [
    {
      "instanceID": "CLUSTER-RES-MEMORY@bke-multi-n1",
      "ruleID": "CLUSTER-RES-MEMORY",
      "name": "Node memory …",
      "status": "FAIL",           // PASS / FAIL / WARN / SKIP
      "subject": "bke-multi-n1",  // 节点名（= spec.hostname）或 "cluster"
      "expected": {"type": "bytes", "value": 17179869184},
      "actual":   {"type": "bytes", "value": 3011952640},
      "evidence": [{"kind": "command", "locator": "bke-multi-n1",
                    "observed": "…", "source": "ssh-node"}],
      "sourceRefs": ["DOC-QUICKSTART"],
      "remediation": "use a node with at least 16 GiB memory",
      "causeCode": "FAIL"
    }
  ]
}
```

要点：

- `instanceID = <ruleID>@<subject>[:<子项>]`，**天然按节点归因**（`subject` 就是节点名）；
- `expected/actual` 是**类型化对象**（`set/bool/integer/bytes/relation`），不要按文本解析；
- `remediation` 是英文可执行建议，可直接喂给 agent 当“下一步”；
- stdout **只有** JSON 一个文档；进度/日志在 stderr（中文“前置检查进度：…”），互不污染；
- 预检**不会改写** `nodes.yaml`（密码仍是明文，文件保持 0600）。

### 本次失败项（正好覆盖“失败措辞”）

| ruleID | 节点 | actual | remediation | 建议映射的错误码 |
| --- | --- | --- | --- | --- |
| `CLUSTER-PLAT-DISTRO` | m1（26.09 例外） | `["openeuler","26.09"]` | use a node distribution/version listed in the preflight policy | `PREFLIGHT_FAILED`（26.09 走已知例外开关） |
| `CLUSTER-PLAT-KERNEL` | m1 | `false` | boot a node kernel covered by the release compatibility matrix | 同上 |
| `CLUSTER-RES-CPU` | n1 | `4` | use a node with at least 8 logical CPUs | `PREFLIGHT_FAILED`（无专属码） |
| `CLUSTER-RES-MEMORY` | n1 | `3011952640` bytes | use a node with at least 16 GiB memory | `MEMORY_INSUFFICIENT` |
| `CLUSTER-RES-SYSTEM-DISK` | n1 | `46683508736` bytes | use a node with at least 100 GiB system disk capacity | `PREFLIGHT_FAILED` |

### 44 条规则（按作用域）

- **节点级**：`PLAT-DISTRO/KERNEL/OS`、`RES-CPU/MEMORY/SYSTEM-DISK`、`PORT-APISERVER/CONTROLLER/SCHEDULER/ETCD-CLIENT/ETCD-PEER/ETCD-METRICS/KUBELET-HEALTH/KUBELET-SECURE/BKEAGENT`、`SSH-TRANSPORT/AUTH/PRIVILEGE`、`SRC-REACHABLE:{image-repo,http-repo,chart-repo}`、`AGENT-SYSTEMD`
- **集群级**：`TOPO-MASTER/ETCD/WORKER/MASTER-ODD`、`UNIQUE-HOSTNAME/UNIQUE-IP`、`NET-POD-CIDR/SERVICE-CIDR`、`ADDON-CLOSURE/SOURCE`、`REF-VERSION`、`MGMT-API/DISCOVERY/CRD-CLUSTER/CRD-NODE/LOCAL-CLUSTER/LOCAL-NODE`、`MGMT-AGENT-KUBECONFIG-SOURCE/GET/PARSE/DATA`、`LOCAL-PATH-ACCESS/CREATE/MOUNT`
- **没有**“spec.hostname 与实际 hostname 是否一致”这条规则（见 Spike 3）。

### 对后端的意义

- 节点校验可以直接**委托**给 `bke preflight cluster-create --output json`：SSH 可达/认证/权限、
  hostname/IP 唯一、CPU/内存/磁盘、目标端口、仓库可达性全在里面，不需要引入 paramiko；
- 本地仍应保留三件**不依赖远端**的快检：hostname RFC1123（BKE 不查）、节点 IP/hostname 去重、角色拓扑；
- 退出码 3 == `ExitCode.PREFLIGHT_FAILED`，**契约天然对齐**，不用另写映射。

---

## Spike 2：`bke cluster scale` 不可用

```bash
bke cluster scale --help   # 输出 bke cluster 的 help，EXIT=0
bke cluster scale          # 同样落到父命令 help，EXIT=0
bke cluster --help         # Available Commands 只有 create / list
```

二进制里确实有文档示例字符串 `bke cluster scale -f … -n …`，但**命令未注册**（cobra 未匹配到子命令时
打印父命令帮助而不是报错，所以会误以为“能用”）。结论：**本期不要依赖 scale**；扩容要么升级 BKE，
要么走“新建 BKENode CR”的未验证路径。

---

## Spike 3：hostname 不一致 = `--hostname-override`

把 `spec.hostname` 故意写成 `worker-1`（实际 OS hostname 是 `localhost.localdomain`），单节点创建。
bkeagent 在节点上的日志（`/var/log/openFuyao/bkeagent.log`）原文：

```text
BKEAgent node hostName: worker-1
OS hostname "localhost.localdomain" differs from BKE node name "worker-1",
  kubelet will register node with --hostname-override
```

即：

1. **不报错**，不中断创建；
2. **不修改** OS hostname（`hostname` 仍是 `localhost.localdomain`，`/etc/hostname` 未变）；
3. k8s 节点名 / 静态 Pod 名用 `spec.hostname`（`etcd-worker-1`、`kube-apiserver-worker-1`…）。

### 设计含义（重要）

- **不需要 SSH 去读远端 hostname**：节点名由用户/agent 给定，BKE 负责 override；
- 但 **RFC1123 必须我们自己校验**：BKE 不校验，带下划线的名字会让静态 Pod 加载失败
  （`etcd-auto_depoly` 事故就是这条路），我们的 `Gate.node` 里 `_evaluate_hostname` 是必需而不是可选；
- 节点名与 OS hostname 不一致会带来运维可见性差异（控制台显示 `worker-1`，机器上 `hostname` 是别的），
  文档要写清；跨节点 `/etc/hosts`、监控采集以 k8s 节点名为准。

---

## 顺带验证的“回退”行为（回答上一轮的疑问）

删除单节点测试集群（`kubectl -n bke-hn delete bkecluster bke-hn`）：

| 现象 | 结果 |
| --- | --- |
| 删 `BKECluster` 级联删 `BKENode` | 是；耗时 **60s**（有等待） |
| 直接删 master 的 `BKENode` | **被 webhook 拒绝**：`master node deletion is not allowed` |
| 删后节点上的 bkeagent / kubelet / containerd | **仍在运行且 enabled** |
| 删后节点上的控制面容器 | **仍在 Running**（etcd、apiserver、controller、scheduler），6443 仍在监听 |
| 删后节点目录 | `/etc/kubernetes`、`/var/lib/kubelet`、`/var/lib/openFuyao`、`/etc/cni`、`/etc/containerd`、`/var/lib/containerd` 全在 |

**结论：删 CR ≠ 节点回退。** 节点必须另外清理（本次已按清单把测试 VM 清干净：停 bkeagent/kubelet/
containerd、删 k8s 容器、删上述目录与 `/usr/local/bin/bkeagent`，hostname 未变、6443 已释放）。

## 环境结论

- 这台 worker 规格 **不达标**：4C（需 8）、2.8 GiB（需 16 GiB）、44 GiB（需 100 GiB），
  预检 3 项 FAIL。可用来测失败路径，但 **不能作为“建出健康多节点集群”的验收机**；
- 网络没问题：同网段 192.168.122.0/24，worker → master 的 40443/40080/38080/36443 全通；
- 你给的 `172.16.178.105:22017` 在本机不可路由，实际等价入口是网关转发 `192.168.122.1:22017`；
  worker 自身 IP 是 `192.168.122.151`，BKENode 里应填这个。

## 附：绿路径复验（2026-10-20 晚，多节点创建 + 应用安装）

前述三项 spike 的结论在真实创建中被再次验证，并补了两条现场结论：

1. **hostname 覆盖确实生效**：worker 的 OS hostname 仍是 `localhost.localdomain`，
   但业务集群里节点名是 `spec.hostname`（`node-2`），`kubectl get nodes` 与
   `BKENode` 名称一致；因此本地 RFC 1123 校验是唯一防线。
2. **`bke cluster create` 会等 addon 部署完才退出**（本次约 10 分钟）：
   期间 `BKECluster.status.conditions` 里 `Addon=False`，但
   `status.ready` 可能已经是 `true`；判定应优先看 `status.ready`，
   条件列表只用于失败归因。
3. **预检 JSON 的 `status` 是大写 `PASS/FAIL`**：按小写匹配会让“预检永远通过”，
   实现里必须大小写无关。

完整实跑记录与复现命令：`docs/openfuyao-stage2-multinode-run-20261020.md`。
