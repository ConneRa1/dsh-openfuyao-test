# PolyMind 桌面端部署与排障（openEuler 虚机）

> 适用：虚机内直接测试 PolyMind 桌面端，不依赖 VS Code 端口转发、nginx 或 Next 服务端。
> 相关方案：`openfuyao-stage2-stage3-automation-plan.md`（桌面端为唯一验收载体）。

## 1. 结构

```text
/opt/polymind-desktop-linux-arm64/      Electron 应用（app://polymind + 内置 /api 代理）
/usr/local/bin/polymind-desktop         启动器（检查/拉起 witty-backend，root 下加 --no-sandbox）
/usr/share/applications/polymind.desktop 桌面项（StartupWMClass=polymind-desktop）
/usr/share/icons/hicolor/256x256/apps/polymind.png
```

运行前提只有一条：`witty-backend` 监听 `127.0.0.1:8000`。**不需要** nginx 3000/3002，也不需要 Next 3001。

## 2. 构建与安装

```bash
# 1) 构建静态产物（约 2-4 分钟）
cd /root/polymind/desktop
npm run build:renderer

# 2) 打包 Electron（受限网络设镜像）
ELECTRON_MIRROR=https://cdn.npmmirror.com/binaries/electron/ \
npx @electron/packager . polymind-desktop --platform=linux --arch=arm64 \
  --out=/opt --overwrite --asar=false --icon=assets/icon.png

# 3) 权限（tester 用户也要能读）
chmod -R a+rX /opt/polymind-desktop-linux-arm64

# 4) 启动器与桌面项（首次安装时）
install -m 755 packaging/polymind-desktop /usr/local/bin/polymind-desktop   # 若已有则跳过
```

更新代码后必须重跑 1)+2)，只重启应用不会加载新的前端产物。

## 3. 启动

- 图形界面：应用列表点 **PolyMind**，或双击桌面图标（`/root/桌面/polymind.desktop`、`/home/tester/桌面/`）。
- 命令行：
  ```bash
  /usr/local/bin/polymind-desktop
  ```
- 环境变量（可选）：
  - `POLYMIND_DESKTOP_API_TARGET`：后端地址，默认 `http://127.0.0.1:8000`；
  - `POLYMIND_AUTH_TOKEN`：默认 `dev-token`；
  - `POLYMIND_DESKTOP_CONSOLE_PORT`：控制台端口，默认 `30010`；
  - `POLYMIND_DESKTOP_APP_DIR`：应用目录覆盖。

root 启动时启动器自动加 `--no-sandbox`；tester 等普通用户不加（沙箱正常）。

## 4. 控制台内嵌

桌面端右侧面板里用 `<webview>` 直接显示控制台，位置与 Web 端 iframe 一致：

- 控制台地址统一改写为 `https://127.0.0.1:<console_port>`（证书 CN 与 host 不匹配，直连 IP 也会失败）；
- 主进程 `will-attach-webview` 校验 src 只允许控制台端口，剥掉 preload/Node，固定
  `persist:polymind-console` 分区；
- 只对 `<console_port>` 放行自签证书，其余仍走 Chromium 默认校验；
- 只放行该 guest 在控制台端口上的 https 跳转（登录/OAuth 回调），外链交系统浏览器；
- 控制台按桌面宽度设计，面板更窄时组件会测量 guest 宽度并整体缩放，避免横向裁切。

为什么不用 iframe：控制台 Cookie 是 `Secure; SameSite=Lax/Strict`，在 `app://polymind` 的跨站
iframe 里不会随子请求发送；`app://` 又是安全上下文，嵌 `http://<host>:3002` 网关还会被混合
内容拦掉。`<webview>` 是独立 guest（按顶层框架加载），SameSite Cookie 正常。

Web 端（3000）仍保留 iframe + 3002 网关的兜底路径。

## 5. 冒烟验证

```bash
cd /opt/polymind-desktop-linux-arm64
POLYMIND_AUTH_TOKEN=dev-token POLYMIND_DESKTOP_HEADLESS=1 POLYMIND_DESKTOP_SMOKE=1 \
POLYMIND_DESKTOP_SMOKE_OUT=/tmp/desktop.png \
xvfb-run -a --server-args="-screen 0 1440x900x24" ./polymind-desktop --no-sandbox
```

检查 `/tmp/desktop.json`：`pageErrors` 为空、`probe.origin=app://polymind`、`probe.hasDesktopBridge=true`。
控制台链路可用 CDP 验证：`--remote-debugging-port=9223`，打开右侧 openFuyao tab 后，
`/json` 里应出现一个 `type=webview`、URL 属于 `https://127.0.0.1:30010` 的目标，标题为
“openFuyao管理平台”；面板内应直接显示登录页。

## 6. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 点击图标无反应 | root 下未加 `--no-sandbox` | 用启动器启动；确认桌面项 Exec 指向 `/usr/local/bin/polymind-desktop` |
| 页面空白/接口 404 | 后端没起 | `systemctl status witty-backend`；启动器会尝试拉起 |
| 控制台区域 `ERR_CERT_AUTHORITY_INVALID` | 证书未放行 | 确认 URL 端口等于 `POLYMIND_DESKTOP_CONSOLE_PORT`；重启应用 |
| 控制台登录后又跳登录 | Cookie 未保持 | 确认控制台是面板内 `<webview>`；清 `persist:polymind-console` 分区后重试 |
| 任务栏图标是默认空白 | `WM_CLASS` 与桌面项不匹配 | `desktop/package.json` 的 `name`、`StartupWMClass` 必须都是 `polymind-desktop` |
| 改了前端没生效 | 未重建 renderer | 重跑 `npm run build:renderer` + 重新 packager |
| 打包体积 299 MB | Electron 运行时本身约 220 MB | 正常；如需更小可在打包后删除 `resources/app/node_modules`（已无可运行依赖） |

## 7. 回滚

```bash
rm -rf /opt/polymind-desktop-linux-arm64
rm -f /usr/local/bin/polymind-desktop /usr/share/applications/polymind.desktop
rm -f /usr/share/icons/hicolor/256x256/apps/polymind.png
```

Web 栈保持原样，可继续用 `http://<host>:3000/` 兜底。
