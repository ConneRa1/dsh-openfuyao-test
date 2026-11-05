# 发布 DSH openFuyao 插件

本仓库有两个相互独立的发布单元。插件**不跟随** `witty-service` 的版本号：

| 发布单元 | tag | 产物 |
| --- | --- | --- |
| witty-service | `v0.2.0` | PyPI、GHCR 镜像 |
| DSH openFuyao 插件 | `dsh-openfuyao-v1.0.0` | 4 个 npm 包、2 个离线 tarball |

## 为什么要 4 个 npm 包

| 包 | 内容 | 何时安装 |
| --- | --- | --- |
| `@openwitty/dsh-openfuyao` | Host：工具、审批、Host 路由 | 用户显式安装 |
| `@openwitty/dsh-openfuyao-panel` | Client：右侧边栏 UI | 由 Host 的 `dependencies` 自动带入，版本必须与 Host 相同 |
| `@openwitty/dsh-openfuyao-sidecar-linux-x64` | 预编译 sidecar | 由 Host 的 `optionalDependencies` 自动带入 |
| `@openwitty/dsh-openfuyao-sidecar-linux-arm64` | 预编译 sidecar | 同上 |

一个 npm 版本只能发布一次，而 sidecar 是 68 MB 的架构相关二进制——两个架构塞不进同一个
tarball。拆成平台包后，`os` / `cpu` 字段让包管理器只装匹配的那一个，用户仍然只敲一条
`dsh plugin add`。

panel 同理：它是 Host 的普通 `dependencies`，Host 的 `cordis.patch.yml` 同时插入
`openfuyao` 和 `openfuyao-panel` 两条 Loader 行。用户只装 Host，右侧栏就自动出现，
不需要再手动 `install_bundle` panel 或往 `dsh.profile.bundles` 里加东西。

## 一次发布的实际流程

```text
1. 手动触发 “Release DSH plugin (version)”
      └─ scripts/dsh-plugin-version.mjs print
           只看 dsh-plugin/ 下的 conventional commits（上次 tag 以来）
           → 下一个版本号，或 none
      └─ git tag dsh-openfuyao-v<ver> && git push origin <tag>

2. tag 自动触发 “Release DSH openFuyao plugin”
      ├─ sidecar 矩阵：ubuntu-24.04(x64) / ubuntu-24.04-arm(arm64)，各自原生构建
      │     └─ npm publish 平台包   ← 必须最先
      │     └─ 生成自包含 tarball
      ├─ npm: panel → Host          ← Host 必须最后
      └─ 把 tarball 挂到 GitHub Release
```

**顺序是硬约束。** npm 对失败的可选依赖只报警告不报错。如果 Host 比平台包先发，用户在
空窗期安装会得到"装好了、但没有二进制"的插件，直到第一次调用才报
`SIDECAR_BINARY_MISSING`。

`release-dsh-plugin.yml` 在发布 Host 前会校验 `optionalDependencies` 是否精确等于本次
版本，不匹配就直接失败。

## 首次发布前的一次性准备

1. **npm scope**：`@openwitty` 组织已存在，且发布账号是成员。
2. **NPM_TOKEN**：仓库 secret，用 granular access token，权限选
   *Read and write* + *Allow bypass 2FA*，scope 限定 `@openwitty`。
3. **确认没有 `private: true`**：两个 `package.json` 都不能有（有则 `npm publish` 直接失败）。
4. **确认 `repository.directory`**：Host 是 `dsh-plugin`，panel 是 `dsh-plugin/panel`。
   npm 页面靠它链回正确的子目录。

## 本地演练（不发布）

```bash
# 1) 看会不会发、发什么版本（只读，跑在真实 git 历史上）
node scripts/dsh-plugin-version.mjs print

# 2) 看内容对不对
npm pack --dry-run ./dsh-plugin            # 应只有 12 个文件，不含 sidecar/
npm pack --dry-run ./dsh-plugin/panel

# 3) 打一个平台包看大小（需要先 ./scripts/build-sidecar.sh）
node scripts/make-sidecar-package.mjs \
  --dist dsh-plugin/sidecar --platform linux-arm64 --version 1.0.0 \
  --out build/npm-pkg/linux-arm64
npm pack --dry-run ./build/npm-pkg/linux-arm64   # ≈33 MB tgz / 68 MB 解包

# 4) 按用户视角在一次性 profile 里装（发布后）
dsh plugin --profile canary add @openwitty/dsh-openfuyao@1.0.0
find ~/.dsh/profiles/canary/node_modules -name witty-openfuyao-sidecar -type f
dsh plugin --profile canary remove @openwitty/dsh-openfuyao
```

第 4 步的 `find` 必须真的有输出。**可选依赖静默缺失是本方案唯一的隐蔽故障**：如果 DSH
的安装策略带了 `--no-optional` 之类，平台包不会被装，插件要到调用时才报错。

## 在沙箱仓里演练流水线

想验证 GitHub Actions 的构建矩阵（尤其是 arm64 runner 上 `pip install -e .` 会不会卡在
`deepseek-harness-sdk`），不要拿正式仓试，也不要往 npmjs 发测试包。

**为什么不能往 npmjs 发测试版**：版本号一旦发布就永久占用，真发布只能跳版本；而且用
`0.1.0-rc.1` 这类预发布号发布时若不带 `--tag`，它会成为 `latest`，用户
`dsh plugin add @openwitty/dsh-openfuyao` 会直接装到测试包。

做法：新建一个测试仓，推当前分支，然后手动触发发布工作流并勾上 `dry_run`：

```bash
git clone --branch split/dsh-openfuyao <本仓库> sandbox
cd sandbox && git remote remove origin
git remote add origin git@github.com:<you>/witty-service-release-sandbox.git
git push -u origin split/dsh-openfuyao:main
```

在测试仓 Actions 里手动运行 **Release DSH openFuyao plugin**，填一个 `version` 并勾
`dry_run`：两个架构照常原生构建、平台包照常打、离线 tarball 照常上传，但**不执行任何
`npm publish`，也不创建 release**。

四个前提：

- 测试仓里必须有**完整 Python 源码**（`src/`、`pyproject.toml`）——sidecar 是从它编的，
  只搬 `dsh-plugin/` 编不出二进制。
- 别用 fork：fork 会继承上游镜像与 force push 的关系。
- `ubuntu-24.04-arm` 在 public 仓免费，private 仓走付费分钟。
- runner 上 pip 直连 PyPI（`[tool.uv] index-url` 只对 uv 生效），不经过本地镜像。

要连"发布语义"（`optionalDependencies` 装不装、`os`/`cpu` 过滤对不对）一起验，把
`setup-node` 的 `registry-url` 指到 `https://npm.pkg.github.com`，`NODE_AUTH_TOKEN` 换成
`${{ secrets.GITHUB_TOKEN }}`，包名 scope 改成仓库 owner，并给 job 加
`permissions: packages: write`。这样 npmjs 上什么都不留。

> `workflow_dispatch` 类型的工作流，只有文件存在于**默认分支**（本仓是 `master`）时才会
> 出现在 Actions 列表里。在 `split/*` 这类分支上看不到是正常的。

## 三条红线

1. **平台包不能有 `dsh` 字段。** 有 `dsh.bundle` 会被 DSH 当成插件行挂载。
2. **平台包不能有 `exports` 字段。** Host 用
   `require.resolve('<pkg>/package.json')` 定位二进制，`exports` 映射会拒绝该子路径，
   直接 `ERR_PACKAGE_PATH_NOT_EXPORTED`。
3. **`SIDECAR_API_VERSION` 必须同一次提交改。** 它同时存在于
   `dsh-plugin/lib/backend.js` 和 `src/witty_service/sidecar/config.py`。改了 Python 侧
   就必须一起发插件，否则握手失败。

## 回滚

```bash
# 用户侧：装回旧版本（npm 保留所有已发布版本）
dsh plugin --profile web add @openwitty/dsh-openfuyao@0.9.3

# 不要指望 npm unpublish：24 小时后需要走 support，且会影响已安装用户
```

离线 tarball 的回滚更直接：Release 里有每个架构的历史附件，换文件即可。

## 已知边界

- **只有 `linux`**。`os: ["linux"]` 意味着 macOS/Windows 用户装上去会得到一个没有二进制的
  Host。`#resolveBinary()` 会在错误里打出平台、试过的路径和补救方式，但不要指望它能工作。
- **配置页没有表单，且刻意不声明 `peerDependencies`**。要出现类型化配置项必须导出
  schemastery `Config`，那会引入 `@deepseek-ai/schemastery` 的 import。而本插件目前主要
  用本地 `link:` 方式安装，pnpm 会为任何声明了 `peerDependencies` 的被链接包打印
  "will not resolve the peer dependencies ... might cause issues"，误导性很强。所以两者
  一起加：先导出 `Config`，再补 `peerDependencies`，不要只补后者。
- **发布不带 provenance**。要开 `--provenance` 需要 `id-token: write` 权限且仓库公开。
