# 可替换前端的平台与连接边界

## 状态与业务归属

设置、provider 配置、显示语言和首次运行引导的权威状态都由本地后端保存。
React/browser、Electron、CLI 和 MCP 读取、修改的是同一组
`/api/v1/settings`、`/api/v1/settings/display-language`、
`/api/v1/onboarding` 和 `/api/v1/onboarding/complete` API。

- `src/webapp/src/utils/configurationProtocol.cjs` 只做 camelCase UI 与 snake_case
  HTTP DTO 之间的转换。配置验证、provider 合并、数据迁移和持久化不在前端实现
- `configurationClient.js` 选择传输方式；`settingsState.js`、`onboardingState.js`
  和 `displayLanguageState.js` 提供 UI 使用的视图数据
- browser 通过 `fetchBackendJson` 访问真实 HTTP API。没有 localStorage 设置后备库，
  不会在后端不可用时把 onboarding 视为完成，也不会把语言保存失败当作成功。
- Electron 配置 transport 使用精确 allowlist 的
  `backend:configuration-request` IPC 转发相同的 canonical DTO。
  该 IPC 只接受六种固定 method/path 组合，不提供任意 URL、文件或 IPC 调用能力
- 两种 transport 都拒绝 redirect；写操作不自动重试。无法确认持久化、返回非法
  状态或 native 同步失败时，调用者必须处理错误，不能宣布全部设置已生效

UI 只使用 `window.vantagePlatform` 窄平台入口，不提供第二套 Electron 业务 IPC。
替换整个前端时，可直接按 `/api/v1` HTTP API/canonical catalog 实现，无需复制
React 或 Electron 中的业务实现。不提供旧 HTTP 路径、旧 origin 存储或旧桥接兼容层。

## 平台能力

`platformAdapter.js` 是 UI 唯一的平台入口。默认 browser adapter 不依赖 Electron。
原生宿主通过隔离后的 `window.vantagePlatform` 对象注入声明与窄操作；其他原生 UI
可以实现同一个边界，或直接调用 HTTP API 加自身 OS adapter。

`getPlatformAdapter()` 返回：

| 接口 | 用途 |
| --- | --- |
| `kind`、`os`、`app` | 平台类型、OS 和宿主版本等展示元数据 |
| `capabilities` | `customTitleBar`、`openSettingsPath`、`pickLegacyRoot`、`launchAtLogin`、`cameraAccess`、`notifications`、`minimizeToTray`、`systemLocale` |
| `window.setTitleBarTheme(theme)` | 仅窗口外观；不是主题的持久化入口 |
| `window.minimizeToTray()` | 托盘隐藏窗口 |
| `paths.openSettingsPath(key)` | 打开允许的配置/历史/日志等目录键，不接受任意路径 |
| `paths.pickLegacyRoot()` | 原生目录选择器；迁移仍由后端执行 |
| `locale.getSystemLocale()` | 原生 OS locale 或 browser locale |
| `camera.requestAccess()` | 宿主可用的相机权限入口；未实现时明确返回 unsupported |
| `notifications.show(title, body)` | 可选原生通知 |
| `preferences.applySaved()` | 重读后端已保存的设置并应用原生副作用 |
| `backend.connection`、`backend.waitUntilReady()` | 连接描述和打包后端启动屏障 |
| `backend.requestJson(method, path, payload)` | 可选的窄配置 transport；browser 用 HTTP |

UI 应依据 capability 启用控件，而不是通过 `kind === 'electron'` 推测功能。
例如当前只有 Windows 的 Electron 主窗口启用了自定义标题栏，其他 OS 不应因此
额外预留标题栏空间。browser 不会假装打开文件夹、选择宿主目录或设置登录启动项。
浏览器仍可保存后端的 `launch_at_login` 偏好，但实际 OS 应用只能由支持该功能的宿主完成。

Electron 保存成功后独立调用 `preferences.applySaved()`，更新登录启动项、托盘语言与
标题栏主题。窗口重新获得焦点时也会重读并应用，因此 CLI/MCP/其他 UI 保存的偏好
可在返回桌面窗口时生效。这里没有增加业务轮询或第二套调度器。组件内展示状态在
下一次读取/重新载入时刷新；原生副作用同步不会替换当前未保存的表单内容。

## 连接规则

JavaScript 的纯模块 `backendConnection.cjs` 供 main、renderer、Vite 代理和 bundled
backend 启动使用。Python/CLI 使用同等语义的连接解析。

1. 显式 backend URL
2. `VANTAGE_BACKEND_URL`
3. `VANTAGE_BACKEND_HOST` / `VANTAGE_BACKEND_PORT`
4. 默认 `http://127.0.0.1:8000`

URL 必须是 HTTP(S)，host 必须为 `localhost`、127/8 的标准点分 IPv4 或 `::1`；
不接受 credentials、query、fragment、端口 0、非 loopback 或非标准数字 IPv4 别名。
支持可选路径前缀。原生请求、相机上传、启动健康检查和 spawned backend 环境都取自
同一个解析结果，不能一部分连自定义端口、一部分继续连接 8000。

- Electron preload 把 main 的实际连接描述传给 renderer。它优先于构建时 URL，避免
  安装后修改端口时 renderer 继续使用旧地址
- 普通 browser 的 HTTP(S) 页面默认使用同源 `/api/v1`、`/static` 路由，且页面源必须是
  loopback。Vite 代理按上述 canonical 环境变量连接后端
- Vite 只读取 `VANTAGE_BACKEND_URL` / `VANTAGE_BACKEND_HOST` /
  `VANTAGE_BACKEND_PORT` 配置同源代理，没有另一组 renderer/proxy 环境变量别名
- 非 Electron 宿主可通过 `window.vantagePlatform.descriptor.backend` 提供 live
  connection。普通 browser 优先使用可信 loopback 同源反向代理；不得放宽 CORS
  到任意来源或关闭 TLS 验证
- HTTPS 或带路径前缀的既有服务可以复用。如果无法连接，Electron 不会尝试把
  plain HTTP bundled backend 启动成一个不兼容的 HTTPS/prefixed endpoint

## 打包应用的同源传输

生产窗口从固定 `vantage://app/index.html` 加载，不再使用 `file://`。
`appProtocol.cjs` 注册 standard、secure、Fetch 和 streaming 能力，保留 CSP 与
`webSecurity`，不开放 `Origin: null` 或通配 CORS。

- `vantage://app` 的 `/api/v1/`、`/static/` 由主进程仅代理到已验证的 loopback 后端；
  `/static/` 只读，其他 URL 只服务真实路径仍在 `dist` 内的已知静态资源类型
- asset realpath 验证阻止符号链接逃逸；host、credentials、路径穿越与代理 redirect
  都被拒绝。代理仅转发必要的内容/范围/intent headers，不传 Cookie、Authorization、
  Origin 或上游 Set-Cookie。传输不缓存整个 NDJSON 响应
- renderer 的 API 和媒体 URL 保持同源。JSON POST 不触发跨域预检；取消响应流只是
  断开该观察连接，取消 job 仍需用户显式触发独立 POST 操作
- Electron 42.8.0 的实际 protocol Request 没有可用的 initiatorOrigin、Origin 或
  referrer。因此 `installAppProtocol` 先在同一 session 注册 webRequest gate，按真实
  webContentsId 和主 frame/可信主文档 URL 放行，再注册 handler。来自其他窗口、
  子 frame、未知 owner 或不可信文档的请求不能进入代理。较新 Electron 若提供
  initiatorOrigin，handler 仍额外核验它
- 窗口仅允许可信主文档导航，禁止新窗口、外部重定向和 webview；CSP 将连接限制在
  self 并禁用 frame/object，未启用 bypassCSP。dev 窗口仍使用 Vite 的同源代理

API 依据已安装 Electron 42.8.0 的 `electron.d.ts` 与官方
[protocol 文档](https://www.electronjs.org/docs/latest/api/protocol) 核验。旧版缺少
initiator 字段的行为还经过真实 Electron renderer 验证，不能只按最新版文档推测。

## 验证范围

`configurationClient.test.js` 用真实 loopback HTTP server 验证 browser/native 两种
transport 的跨入口读写、零值/局部更新、onboarding、语言保存、redirect 拒绝及错误
传播；它是 transport 合约测试，服务端业务与真实持久化由 Python endpoint 测试覆盖。
`backendConnection.test.js`、`backendRequest.test.js` 和 `backendRuntime.test.js` 覆盖
连接优先级、安全边界、启动探测与 spawn 环境一致性。`main.test.js` 的启动屏障测试
运行真实本地 HTTP transport；mapper 测试直接调用共享模块而不是复制实现。

运行 `npm --prefix src/webapp run check`，以及安装 Electron binary 后的
`npm --prefix src/webapp run test:electron-protocol`。后者使用临时合成数据、真实隔离
preload、生产协议 handler 和 offscreen renderer；验证 secure origin、JS/image
assets、无预检 JSON POST、第一条 NDJSON 在连接结束前抵达、Abort 关闭观察但任务
继续完成，以及第二个不可信窗口被拦。Linux 使用 Ozone headless，不关闭 sandbox。
Windows/macOS 安装包的相机、登录项、托盘、
通知与标题栏仍需对应 OS 的实际安装验收，源码测试和 Vite 构建不等同于安装验收。
