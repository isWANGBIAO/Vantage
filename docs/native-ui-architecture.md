# 可替换原生 UI 的应用边界

Vantage 的业务后端与界面独立运行。React + Electron、Windows WinUI 3、macOS SwiftUI 和 Linux GTK4 客户端复用同一 HTTP 服务、持久设置与后台行动计划调度，无需移植 React 的业务定时器。原生应用入口、构建和验证边界见 [原生客户端](native-clients.md)。

## 分层与职责

- `src/server.py`：FastAPI 组装、路由注册与启动入口
- `src/backend/`：设置/引导、行动计划、聊天、provider、财务、人脸、媒体、相机、图表、健康、项目等职责模块；HTTP 适配和既有领域实现按职责组织
- `src/backend/application.py`：将领域函数接入任务/调度服务，提供版本化 HTTP 应用接口
- `src/services/action_plan_jobs.py`：无 FastAPI、React、Electron 依赖的单运行任务服务，依赖注入生成器、结果读取和来源版本
- `src/services/action_plan_scheduler.py`：无 GUI 依赖的后台策略、动态设置、版本记录与重试
- `src/services/action_plan_store.py`：暂存、完整性验证和结果原子发布，不依赖任何 UI
- `src/core/` 与其他 `src/services/`：配置、持久化、模型客户端及可复用业务组件
- `src/webapp/src/utils/actionPlanJobs.js`：只负责提交、观察、重连、取消的客户端适配
- `src/webapp/src/utils/platformAdapter.js`：原生窗口、文件选择、系统区域、权限、后端连接等平台能力

并非所有领域函数都已经成为无 HTTP 的纯业务类；现有功能按职责独立成模块，长任务/调度则已抽成可直接注入测试的应用服务。新增功能应优先写服务，由窄路由调用，避免重新堆入入口文件。

## 连接与安全边界

运行时统一优先级：显式客户端地址 → `VANTAGE_BACKEND_URL` → `VANTAGE_BACKEND_HOST` / `VANTAGE_BACKEND_PORT` → `http://127.0.0.1:8000`。Electron 主进程把解析结果交给 renderer；CLI/MCP 使用相同的 Python 规则。Vite 使用同一组 canonical 配置，详见平台适配文档。

仅允许 loopback HTTP(S)，禁止用户信息、查询串和 fragment。客户端可连接本机 HTTPS/path-prefix 代理，但内置后端不会把代理 URL 当作可启动的 plain HTTP 地址。此架构没有提供网络账户、远程授权或 LAN/public 部署；不要把服务暴露到公网。保留单后端进程/单 worker 运行方式，当前任务互斥和硬件状态是进程内的。

全局 ASGI 边界对所有 HTTP 与 WebSocket（包括媒体资源）校验客户端和 Host 为 loopback；有 Origin 的浏览器请求须来自开发白名单，显式 null 或不可信 Origin 在派发前拒绝，防止无预检的跨站 POST。开发 CORS 只允许受信任的本机 Vite 来源。Electron 配置调用通过精确路径/方法 allowlist 的窄 IPC 转发至同一 HTTP 配置 API；生产 renderer 使用可信 `vantage://app` 同源协议访问打包资源与后端流，开发 browser 通过同源代理访问。无需允许不可信的 `Origin: null` 或禁用 webSecurity。API 密钥始终 write-only/脱敏，不再将浏览器 localStorage 当作业务配置存储。

## 原生客户端接入步骤

1. 由应用宿主启动或连接唯一后端，等待 `/api/v1/system/status` 成功；不要每个页面启动服务
2. GET `/api/v1/capabilities`，确认 `api_version` 主版本与所需能力
3. GET `/api/v1/operations` 取得稳定操作名、路径、输入 schema、副作用和敏感性说明；完整 HTTP schema 为 `/openapi.json`
4. 读取 `/api/v1/onboarding` 和 `/api/v1/settings`，把后端作为唯一配置来源；完成引导后由宿主应用原生副作用
5. 读取 `/api/v1/action-plan/today` 显示保存结果，GET `/api/v1/action-plan/jobs` 发现正在运行或最近完成的任务
6. 用户点击生成时 POST `/api/v1/action-plan/jobs`；观察任务状态和事件；停止时调用显式 cancel
7. 将窗口、托盘、登录启动、权限、文件选择、剪贴板、系统 locale 等适配到本平台；缺少能力时禁用对应控件或说明限制

可复用的 JSON DTO schema 位于 [contracts/application-v1.json](contracts/application-v1.json)，由 `python -m scripts.export_api_contracts` 生成并通过快照测试防止未同步的变更。客户端应忽略未知响应字段；破坏性契约变更需新主版本。所有客户端同时使用唯一 `/api/v1` 契约。旧 `/api/*` 与 `/api/automation/*` 入口、重复生成流、Python server façade 和 Electron 旧桥均已删除，不提供兼容路由。

## 行动计划任务协议

| 操作 | HTTP |
| --- | --- |
| 创建/加入任务 | POST `/api/v1/action-plan/jobs` |
| 当前和最近任务 | GET `/api/v1/action-plan/jobs` |
| 单任务快照 | GET `/api/v1/action-plan/jobs/{id}` |
| 可重连 NDJSON | GET `/api/v1/action-plan/jobs/{id}/events?after={sequence}` |
| 显式取消 | POST `/api/v1/action-plan/jobs/{id}/cancel` |
| 调度状态 | GET `/api/v1/action-plan/scheduler` |

创建参数延续 `reasoning_effort`、`service_tier`、`model`、`provider_route`、`replace_today`、`wait_for_provider_ready`。响应为 202 和任务快照。已有 active job 时，不论请求来自哪个 UI/CLI/自动任务，都返回该任务且 `reused=true`；不会覆盖其参数或再启动模型。客户端应展示实际返回的 request，避免误认为新参数已执行。

状态为 `queued → running → succeeded | failed | cancelled`，取消中可见 `cancelling`。失败提供安全的 `{code,message}`；`result` 为完整今日计划响应，包括 `analysis`、`plan`、`meta`、`date`、`filename`、`id`。只有生成器无错误地结束、明确完成且验证有新的完整保存结果，才标记成功。生成器将计划和上下文先写入本次独立暂存目录，usage 数据库保持原位置。流完整成功后验证新 JSON/日期，再原子发布唯一文件名；请求替换时仅在发布后清理旧计划。失败、进程崩溃或重新打开界面都不会读到暂存输出。

事件具有单调 `sequence`，客户端记录最后收到的序号重连并去重。任务最多保留 32 个，每任务事件保留最多 256 条 / 2 MiB，单条 NDJSON 输入上限 1 MiB；计划文件上限 32 MiB。事件与任务是有界内存记录；收到 `truncated`/`event_truncated` 应停止拼接不完整正文并重新读取任务快照，不能把丢失片段当成功。EOF 或非空正文不代表完成。后端重新启动后任务 ID 可 404，客户端应回读保存结果和新的任务列表；不承诺恢复被杀死的模型子进程。

HTTP 断开、切页、关闭 renderer、观察超时都不会取消后端任务。显式 cancel 等待生成器清理，终止并回收生成子进程。整个后端退出会关闭调度并取消未完成任务。生成只使用 jobs 接口；客户端须显式取消任务，不能依赖中断 HTTP 取消。

## 后台策略和 UI 定时器

- `action_plan_auto_generate` 控制后端启动/跨日后缺少完整今日计划的生成；只有 onboarding 完成后才执行
- `action_plan_check_interval_minutes` 独立控制源版本检查，0 关闭版本检查；设置从后端动态读取，不依赖 UI 重载
- 指纹覆盖必要工作簿与相关可选资料；首次已有计划建立基线，之后源变化才生成，成功才推进已消费版本
- 调度元数据原子写入配置的 runtime 目录，仅保存日期、指纹与不透明结果标识；不保存正文、提示词或密钥
- 自动生成使用后端 provider 配置的默认模型；某个 UI 的未提交模型选择是该 UI 的下一次手动请求选项，不改变自动调度默认模型
- 后台失败保持上次完整显示结果；前端可显示失败状态与最后成功内容
- UI 时钟、录音显示、复制反馈、流渲染节流、只读状态轮询仍是展示职责，不迁入后台调度

## 验证与边界

注入式任务/调度测试不连接真实模型；HTTP 测试覆盖去重、取消、完成门槛与契约；前端行为测试覆盖重连、截断、Stop 与组件卸载；原有领域回归和构建继续保留。相机权限、托盘、安装包、DPI 和 Windows/macOS 原生体验仍须在相应系统实际验收，Linux 单元测试不能证明这些体验通过。

本次未改写聊天流的持久任务协议，聊天仍使用原有 HTTP 流；人脸历史分析仍复用现有后端 job/progress API。它们的业务都位于后端，后续可以在独立版本迭代中扩展统一任务类型，无需重写 UI 调度。

## 聊天、凭据与持久化

`/api/v1/chat/context` 返回完整可见 `messages` 与 `context_version`，每项只有 user/assistant role 和 content，不包含模型系统指令或分析输入。界面读取后端权威快照，清空动作直接采用 DELETE 返回的新状态，不以 localStorage 或不变的计划 base version 恢复旧消息。聊天流按会话串行，文件写入原子化；revision/CAS 阻止重置或新计划发布后旧请求覆盖新上下文。

设置/引导、聊天状态、调度状态与流事件均有正式 DTO；OpenAPI 的 NDJSON 媒体类型为 `application/x-ndjson`，`x-ndjson-item-schema` 指向每行事件的联合类型，导出的 JSON schema 同时供不支持流扩展的客户端生成事件模型。不存在“application/json 空对象代表流”的隐式约定。

保存的 provider key 与原始 API 目的地绑定。改写目的地时省略/掩码 key 不会把旧密钥带过去；保存时需要显式重新提供凭据或明确清除旧密钥，模型发现也不会跨目的地复用密钥。配置采用临时文件+fsync+原子替换，已有损坏 JSON 会报错并保留原字节，不静默覆盖默认值。引导先保存 provider/迁移状态、最后提交 completed；失败回滚配置文件，避免半成功被报告为完成。
