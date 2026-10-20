# openFuyao 阶段 2 多节点实跑报告（2026-10-20 晚）

## 结论

- **阶段 2 多节点已跑通**：`bke-multi` = 本地 master `auto-depoly`(192.168.122.146)
  + 已有机器 worker `node-2`(192.168.122.151)，两台 `Ready`，BKE 状态
  `ClusterReady / Healthy / Ready`，耗时约 10 分钟。
- **阶段 3 已跑通**：`nginx-demo` 通过 `helm upgrade --install` 部署到 `default`，
  Pod `1/1 Running`，NodePort `32424` 返回 `HTTP 200`。
- 全链路只经后端 API + CLI，**没有在 agent/CLI 里出现节点密码**，也没有直连 `bke`。

## 实际执行（可复现）

```bash
# 1) 同步预检（L1 + bke preflight --output json）
witty-service openfuyao cluster preflight \
  --agent-id <agent> --node ip=192.168.122.151,hostname=node-2
# exit 0；62 项中 60 通过，2 项为本地 OS/内核矩阵例外（已按
# OPENFUYAO_ALLOW_UNSUPPORTED_OS=true 记为 tolerated）

# 2) 创建：本地 master 自动补全，worker 由 --node 给出
witty-service openfuyao cluster create --name bke-multi \
  --node ip=192.168.122.151,hostname=node-2,role=worker \
  --confirm --wait --json
# exit 0；nodes 均为 ready；endpoint=https://192.168.122.146:6443

# 3) 安装应用（chart 在主机侧目录，密码/凭据不经过 CLI）
witty-service openfuyao app install --cluster bke-multi --release nginx-demo \
  --chart-dir /var/lib/witty-service/.witty/openfuyao/charts/nginx-demo \
  --image docker.m.daocloud.io/bitnami/nginx:latest --node-port 32424 \
  --confirm --wait --json
# exit 0；status=deployed；verify_url=http://192.168.122.146:32424/
```

验收证据：

```bash
kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes
# auto-depoly   Ready  control-plane,master,node,worker
# node-2        Ready  node,worker

kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n bke-multi get bkecluster
# bke-multi  ClusterReady  Healthy  Ready  2/2

curl -s -o /dev/null -w '%{http_code}\n' http://192.168.122.146:32424/   # 200
```

## 验证到的设计点

| 设计点 | 结果 |
| --- | --- |
| 多文档 `nodes.yaml`（1 master + N worker） | BKE 接受，一次提交 1 BKECluster + 2 BKENode |
| `spec.hostname` 与远端真实 hostname 不一致 | worker 实际 `localhost.localdomain`，注册为 `node-2`，**不报错**（`--hostname-override`），RFC 1123 必须由我们校验 |
| 预检 JSON 映射 | `--output json` 退出码 3/0；`results[].status` 是 **大写 `PASS/FAIL`**（本轮踩过，已修） |
| 失败归因 | 预检失败项按 `subject` 落到 `openfuyao_cluster_nodes.error_code/last_message` |
| 幂等 | 同 name + 同节点集再次 create：秒回 `ready`，不重跑 bke |
| 负例：hostname `node_2` | CLI 退出 **3**，`HOSTNAME_INVALID`，未执行任何 bke 命令 |
| 负例：节点无凭据 | CLI 退出 **3**，`NODE_CREDENTIAL_MISSING`，错误信息给出凭据文件路径 |
| destroy 未带 `--confirm` | 退出 **2**，不删任何资源 |

## 本轮修复的问题（均已补单测）

1. **预检状态大小写**：只匹配小写 `fail`，而 BKE 返回 `FAIL`，会导致“预检永远通过”。
   现改为大小写无关，并抽出 `failed_results()` 单测。
2. **`AppRunner` 漏存 `on_progress`**：`run()` 第一步即 `AttributeError`，落成
   `APP_INSTALL_FAILED`。已补回归测试。
3. **Pod condition 是字符串 `"True"`**：按布尔判断导致 verifying 永远不结束。已修。
4. **Bitnami nginx 监听 8080**：演示 chart 的 80 端口探针一直失败；chart 改为 8080
   （`containerPort/targetPort/probe`），与镜像行为对齐。

## 已知限制（明确不做/待后续）

1. **面板节点表未做**：本期只交付后端 + CLI；桌面端仍是阶段 1 的环境面板。
2. **建好后扩容**：`bke cluster scale` 未注册，依赖它才能做，本期不支持。
3. **销毁不清理节点**：只删 `BKECluster`（等 finalizer）。删完 worker 上 kubelet/containerd
   仍在跑、6443 仍监听；`cluster destroy --json` 会返回 `nodes_dirty` 清单，需重装节点
   或手工清理。自动化里**禁止** `bke reset`。
4. **应用市场 API 未接**：阶段 3 走 `helm`，市场里能看到同名 release；若必须“从市场点安装”，
   还需接 marketplace REST/OAuth。
5. **chart 目录必须是后端本机路径**：API 在服务端校验目录存在；当前只支持同机。
6. **演示 chart 的镜像来自 `docker.m.daocloud.io`**：官方 Bitnami OCI 在本网络不可达；
   正式交付应镜像到内网仓库并去掉 `global.security.allowInsecureImages`。

## 凭据与安全

- 节点密码只在 `/var/lib/witty-service/.witty/openfuyao/nodes.cred`（0600，
  `witty-service:witty-service`），按 IP 索引；
- 渲染出的 `cluster.yaml/nodes.yaml` 在 `<work_dir>/<cluster_id>/bundle/`，0700/0600，
  `finally` 删除；数据库只有 IP/hostname/角色，没有密码；
- 后端以 `witty-service` 运行，`bke`/`kubectl`/`helm` 走 `sudo -n` 白名单
  （`/etc/sudoers.d/90-witty-openfuyao`、`91-witty-openfuyao-cluster`）。

## 环境备注

- worker VM 现为 8 vCPU / 20 GiB（MemTotal 18.4 GiB）/ 根分区 108 GiB，
  满足 BKE 的 8C/16GiB/100GiB 门禁；
- 调整磁盘时 `virsh blockresize` 未带单位，worker 的 **qcow2 虚拟容量被放大到 120T**
  （稀疏文件，实际使用约 2.3 GiB；根分区 108 GiB 是正常的）。不影响本次运行与预检，
  但**不要在这个 VM 上做整盘快照/镜像导出**；彻底修复需关机后 `qemu-img resize --shrink`
  并重建 GPT 备份头，建议等业务集群销毁后单独处理；
- 管理 k3s 在 36443，业务集群在 6443；`/root/.kube/config` 仍指向管理面，
  业务面请显式用 `/etc/kubernetes/admin.conf`。
