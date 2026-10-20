# openFuyao Phase 0：环境与兼容性门禁记录

> 执行日期：2026-10-19 ~ 2026-10-20
> 执行机：KVM 虚拟机 `auto_depoly`（openEuler 26.09，aarch64）
> 门禁命令：`witty-service openfuyao preflight`
> 结论：**自动门禁通过（0 fail / 3 warn）**；`bke init` 在切到 cgroup v1 后
> 于 2026-10-20 实机通过，详见 3.1 与第 4 节。

---

## 1. 本机事实

| 项 | 实测 | 门禁阈值 | 判定 |
| --- | --- | --- | --- |
| OS | openEuler 26.09（ID=openEuler） | 26.09 | PASS |
| 架构 | aarch64 | x86_64 / aarch64 | PASS |
| CPU | 8 核 | ≥8（AIO） | PASS |
| 内存 | 总 14.5 GiB，可用约 11 GiB | 推荐 16 GiB | WARN |
| 系统盘 | `/` 总量 113.3 GiB，可用 94.4 GiB | 建议可用 ≥100 GiB | WARN |
| 权限 | root | root / sudo | PASS |
| tar | 已安装 | 必需 | PASS |
| Docker/K8s 残留 | 无（docker/k3s/containerd 均未安装） | 无残留 | PASS |
| 端口 30010/6443/80/443 | 均空闲 | 均空闲 | PASS |
| 安装源 | OBS、`cr.openfuyao.cn`、`charts.bitnami.com` TCP 443 可达 | 可达 | PASS |
| NTP | `NTPSynchronized=no`，UDP/123 无监听 | 建议已同步 | WARN |

### 1.1 实测输出

```text
openFuyao 快检  host=192.168.122.146
[PASS] 操作系统         openEuler 26.09
[PASS] CPU 架构       aarch64
[PASS] CPU 核数       8 核
[WARN] 内存           总内存 14.5 GiB，低于推荐 16 GiB；同机运行 PolyMind 需保留 2 GiB
[WARN] 系统盘          总 113.3 GiB、可用 94.4 GiB；建议可用 ≥100 GiB
[PASS] 执行权限         root 权限可用
[PASS] tar 依赖       tar 已安装
[PASS] 宿主机清洁度       未检测到 Docker/K8s 残留
[PASS] 端口占用         30010/6443/80/443 均空闲
[PASS] 安装源连通性       BKE 下载源、镜像仓库、应用市场均可达
[WARN] NTP 校时       系统时钟未同步；UDP/123 不可达时请设置 OPENFUYAO_ENABLE_NTP=false
结论：通过（pass=8 warn=3 fail=0）
```

> 内存按 16 GB 规格分配，系统可用总量为 14.5 GiB（`MemTotal=15177532 kB`）；系统盘按
> 128 GB 规格分配，根文件系统为 113.3 GiB。两者属于虚拟化/文件系统开销导致的
> “名义规格达标、账面值略低”，因此记 WARN 而不是 FAIL，但验收机仍建议 16 GiB/100 GiB 可用。

---

## 2. BKE 安装介质校验

不执行安装脚本，只验证下载链路与校验和：

```bash
curl -fsSL -o download.sh \
  https://openfuyao.obs.cn-north-4.myhuaweicloud.com/openFuyao/bkeadm/releases/download/latest/download.sh
curl -fsSL -o download.sh.sha256 \
  https://openfuyao.obs.cn-north-4.myhuaweicloud.com/openFuyao/bkeadm/releases/download/latest/download.sh.sha256
sha256sum download.sh
```

结果：

```text
官网 .sha256 内容：e6e2ecf1305e69cd30bc37a4ad92d1ef041d1660d20be1949f408235af655834  -
实测 download.sh：e6e2ecf1305e69cd30bc37a4ad92d1ef041d1660d20be1949f408235af655834
```

注意：官网 `.sha256` 的文件名列是 `-`（按 stdin 生成），直接 `sha256sum -c` 会因文件名
不匹配失败。Runner 必须**比较哈希字符串**，不能依赖 `sha256sum -c`。

---

## 3. 26.09 兼容性风险

- 快速入门文档基线是 openEuler 22.03 LTS；本方案按需求保持 26.09。
- 上游 skill 已记录：26.09 / kernel 6.6 可能触发 `bke preflight` 的“发行版/内核不受支持”，
  但引导节点实际可以完成。该类**仅限 OS/内核矩阵**的失败属于已知例外，需要用户确认后继续；
  端口、内存、磁盘、镜像源、依赖类失败不得跳过。
- Phase 0 端到端必须在干净 8C/16G 机器上确认；本机仅验证了只读门禁。

---

### 3.1 2026-10-20 实机尝试结果（快照 snap-20261019）

在快照就绪后实际执行了 `bke init`，结论是 **26.09 默认 cgroup v2 下 BKE 引导集群无法启动**：

- `bke preflight init`：18 项中 16 通过，仅“主机发行版及版本”“内核兼容性”两项失败；
- `bke init`：containerd 安装成功，k3s 容器反复重启，日志报
  `failed to find cpu cgroup (v2)`；
- 宿主机 `/sys/fs/cgroup` 为 cgroup2，根 `cgroup.controllers` 含 `cpu`，但
  `cgroup.subtree_control` 无法启用 `cpu`，`/sys/fs/cgroup/cpu.max` 不存在；
  k3s 容器内 `RootControllers()` 找不到 `cpu`，因此拒绝启动；
- 已执行 `bke reset --all --mount --confirm` 清理，网络/端口/服务恢复正常，
  `/bke` 已删除；`bke` 二进制保留以便重试。

处理路径中，**方案 2 已验证可行**：内核 cmdline 增加
`systemd.unified_cgroup_hierarchy=0` 并重启后，宿主为 cgroup v1 混合模式
（`/sys/fs/cgroup` 为 tmpfs，`/sys/fs/cgroup/cpu/cpu.cfs_quota_us` 存在）。
2026-10-20 09:52 重跑 `bke init`，约 4 分钟完成，出现
`BKE initialization is complete`，控制台 `:30010` 返回 302 到 OAuth，Pod 全部
Running/Completed。`bke preflight init` 仍只有 OS/内核矩阵两项失败，需
`OPENFUYAO_ALLOW_UNSUPPORTED_OS=true` 放行。

备选仍是 **换 22.03**（快速入门基线，风险最低）；`--cgroupns=host` 仅作实验，
不推荐交付。

## 4. 实机步骤与待办

本机在快照 `snap-20261019` 后执行了 `bke init`（会安装 k3s/containerd、调整网络/NTP，
属于宿主级破坏性操作）。回退流程见
[openfuyao-host-reset-runbook.md](openfuyao-host-reset-runbook.md)。后续机器按以下顺序：

1. 准备干净 8C/16G、可用 ≥100 GiB、openEuler 26.09 虚拟机，并做快照；
2. 运行 `witty-service openfuyao preflight`，要求 0 FAIL；
3. 安装 BKE 并执行 `bke preflight init`，记录 26.09 的矩阵告警；
4. 执行 `bke init ... --installConsole=true`，确认日志出现
   `BKE initialization is complete`，Pod 全部 Running/Completed；
5. 在控制台完成阶段 2（新增单节点业务集群）与阶段 3（应用市场安装 nginx）；
6. 记录耗时、失败点、资源水位，回填本文件；
7. 如 26.09 无法完成业务集群/应用，按决策点回退 22.03，不静默降级。

对应的自动化编排在 Phase 1 落地；Phase 1 的单测与失败注入不依赖真实 BKE。

---

## 5. 复现

```bash
cd /root/witty-service
.venv/bin/python -m witty_service.openfuyao_cli preflight
# 或进入安装后的 PATH：
witty-service openfuyao preflight
# 机器可读：
witty-service openfuyao preflight --json
```

退出码：`0` 表示无 FAIL（允许 WARN）；`1` 表示存在 FAIL，按输出逐项处理。
