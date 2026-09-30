# Vantage 项目记忆

这份文件是 Vantage 项目的模型交接与操作参考，保存在 Vantage 仓库中，供 CLI、MCP 和项目 Skill 共用；它不是 AGENTS.md，也不取代仓库级协作规则。

## 事实优先级与隐私边界

出现冲突时按以下顺序核实：当前源代码 → 当前测试 → 当前运行日志和实际端点 → 设计文档 → 实施计划 → README。本文件可能落后于代码，涉及接口、参数、能力或运行状态时先核对对应源文件和测试。

Source code > tests > runtime evidence > design documents > plans > README.

Vantage 是公开仓库。不要将用户的私有提示词、聊天内容、照片、健康数据、财务工作簿、运行日志、API 密钥或机器专属路径写入仓库、示例、提交或问题报告。运行时数据写入 Vantage 配置的用户数据目录，不写入源码目录。

## 架构与运行边界

- 桌面端是 Electron + React；本地 FastAPI 后端承载产品 API 和业务规则。开发默认后端地址为 127.0.0.1:8000。
- 自动化目录位于 src/services/automation_catalog.py；稳定操作名、描述、参数 JSON Schema、输出类型和可用性在这里定义。前端仍使用现有 API/Electron 能力，CLI 与 MCP 复用同一目录和 src/services/vantage_client.py，不应复制业务规则。
- HTTP 服务和既有配置服务是设置与业务数据的权威入口。src/core/user_config.py 负责配置验证/脱敏和 JSON 持久化；src/core/config.py 根据应用模式与环境变量解析用户数据、配置、历史、日志、缓存等目录。不要假定或硬编码某台机器上的绝对路径。
- 已安装 Windows 应用把 CLI/MCP 分流到现有 VantageBackend.exe；不应启动 Electron 窗口、第二个 Python runtime 或第二个 API 服务。服务端入口和 PyInstaller 配置分别见 src/scripts/run_server_background.py 与 src/core/backend_runtime_packaging.py。
- MCP 默认使用本地 stdio。启动 Vantage MCP 前须确保现有 Vantage 后端已运行；MCP 只复用它。协议数据走 stdout，诊断信息走 stderr。

## 使用入口

- 源码工作区：python -m src.cli --help；MCP 为 python -m src.cli mcp。
- Windows 安装版：vantage --help；MCP 为 vantage mcp。安装版命令通过现有后端 runtime 工作，不会自行拉起桌面或后端服务。
- CLI 命令按操作名逐段生成，例如 action_plan.today.read 对应 vantage action-plan today read。先运行帮助查看参数，不要猜测命令或工具名。
- CLI 支持 text/json；流式响应按 NDJSON 逐行输出。文件下载可用 --output 指定目标；涉及复杂或敏感值时优先从标准输入传 UTF-8 JSON：--input-json -，避免把密钥放入 shell 历史或进程参数。
- MCP 工具使用 catalog 中的稳定操作名；vantage://catalog 列出全目录，vantage://operations/<操作名> 提供单项元数据。桌面专属操作仍会出现在目录中，但调用时会解释不可用原因；不能据此臆造其已支持自动化。
- 操作发现路径：CLI 用 vantage --help 和对应子命令 --help；MCP 用工具列表或 catalog 资源。优先选精确的单项能力，而不是尝试内部 API 或拼造新操作。

## 设置安全与验证

读取当前脱敏设置可用 settings.state.read（CLI：vantage settings state read）。写设置用 settings.update（CLI：vantage settings update），仅提交用户要求更改的最小字段，然后再次读取设置确认实际保存结果。

重要语义：

- action_plan_auto_generate 控制后端启动/跨日时缺少完整今日计划的自动生成；action_plan_check_interval_minutes 独立控制后端数据版本检查。间隔为 0 只关闭版本检查，所有自动生成均等待 onboarding_completed。多个前端不创建多份调度。
- provider_config 中省略的顶层字段保持原值；若传入 providers 字典，它会替换完整 provider 集合，包括传空字典。因此，未经用户明确要求不得把不完整 providers 字典写回。
- API key 是 write-only，响应中会脱敏；需要提供密钥时用标准输入 JSON，不能回显、记录或放到命令行参数。
- 写操作后必须从共享读取入口再次确认；若后端失败或状态不明确，不要声称设置已生效。

CLI/MCP 对 settings.update、settings.display_language.update 和 onboarding.complete 的确认仅表示共享 JSON 已保存；登录启动项、托盘标签等 Electron 原生效果由桌面 UI 应用。CLI/MCP 修改行动计划间隔由后端调度器动态读取，无需重载界面。间隔有效范围为 0–35,791 分钟。

调用 onboarding.complete 必须显式提供 skip_chat_setup。设为 true 会保留已有 provider 配置；设为 false 时必须提供 selected_provider，更新只合并该 provider，不会删除其它 provider、模型参数或已保存密钥。
启用 import_legacy_data=true 时必须显式提供 legacy_root；catalog schema 会表达此条件，服务端仍负责最终路径校验。

有副作用的读取与工具：face.live.read 的 active=true 会标记实时查看器处于可见状态；system.media.open_folder 会打开操作系统文件管理器。调用前确认这正是用户要求的动作。

## 行动计划工作流与边界

人工读取当前今日计划使用 action_plan.today.read；生成使用 action_plan.jobs.create，观察使用 action_plan.jobs.events，状态使用 action_plan.jobs.read。要替换今天已保存的计划，显式设置 replace_today=true。创建返回任务快照与ID，events操作返回NDJSON进度流；只有收到明确的 done=true 且未收到 error/STREAM_ERROR，才可视为生成成功。完成后再次调用 action_plan.today.read，检查最新日期、分析与计划内容是否完整，再对外说明已经更新。失败、超时、缺少完成事件或响应不完整时，不得把旧计划说成新结果，也不得向用户声称替换成功。

“每隔 N 分钟自动检查数据变化”现在由 src/services/action_plan_scheduler.py 在后端生命周期内运行。成功版本与来源指纹保存在运行目录的原子元数据文件中；失败不会推进版本。React 只读轮询任务状态、显示进度和接受用户发起/取消，不触发定时生成。新版原生客户端可使用 /api/v1/capabilities、/api/v1/operations 和 /openapi.json 发现协议，详见 docs/native-ui-architecture.md。

行动计划只通过 canonical /api/v1/action-plan/jobs 进入单一 ActionPlanJobService。action_plan.jobs.create 返回稳定任务 ID；重复请求合并到正在运行的任务，响应 reused=true。断开观察不会取消生成；需显式调用 action_plan.jobs.cancel。任务仅在收到完成信号且验证新保存结果完整后成功。事件只做有界进程内保留；后端重启后任务 ID 可失效，已保存计划不丢失。

## 用户可见操作映射

下表由当前 automation catalog 与 CLI 命令生成规则整理。MCP 工具名与第二列相同；目录中标为 desktop_only 的工具是可发现但不能从 CLI/MCP 完成的窄桌面动作，应通过 Vantage 可见 UI/电脑操作。

| Vantage 界面能力 | Catalog / MCP 工具 | CLI 命令 |
| --- | --- | --- |
| 后端版本与能力 | system.capabilities.read | vantage system capabilities read |
| 行动计划来源版本 | action_plan.source_revision.read | vantage action-plan source-revision read |
| 创建/加入行动计划任务 | action_plan.jobs.create | vantage action-plan jobs create |
| 列出行动计划任务 | action_plan.jobs.list | vantage action-plan jobs list |
| 读取任务 | action_plan.jobs.read | vantage action-plan jobs read |
| 观察任务事件 | action_plan.jobs.events | vantage action-plan jobs events |
| 显式取消任务 | action_plan.jobs.cancel | vantage action-plan jobs cancel |
| 后端调度状态 | action_plan.scheduler.read | vantage action-plan scheduler read |
| 服务与相机状态 | system.status.read | vantage system status read |
| CPU、内存、磁盘及媒体存储统计 | system.statistics.read | vantage system statistics read |
| 相机检测框显示切换 | system.detection.toggle | vantage system detection toggle |
| 在系统文件管理器打开照片/截图目录 | system.media.open_folder | vantage system media open-folder |
| 当前可信位置的空气质量 | system.air_quality.read | vantage system air-quality read |
| 最新照片/截图及扫描状态 | system.media.latest.read | vantage system media latest read |
| 久坐状态 | sedentary.read | vantage sedentary read |
| 刷新仪表盘图表缓存 | plots.refresh | vantage plots refresh |
| 读取仪表盘图表 | plots.read | vantage plots read |
| 读取今日行动计划 | action_plan.today.read | vantage action-plan today read |
| 读取聊天上下文 | chat.context.read | vantage chat context read |
| 重置聊天上下文 | chat.context.reset | vantage chat context reset |
| 读取模型用量 | usage.read | vantage usage read |
| 列出已配置模型 | models.list | vantage models list |
| 发现特殊 provider 模型 | providers.special_models.discover | vantage providers special-models discover |
| 发现模型 | models.discover | vantage models discover |
| 向模型发送聊天并读取流 | chat.send | vantage chat send |
| 转录本地音频文件 | media.transcribe | vantage media transcribe |
| 读取近期后端日志 | logs.read | vantage logs read |
| 读取采购建议 | finance.recommendations.read | vantage finance recommendations read |
| 重新生成采购建议 | finance.recommendations.regenerate | vantage finance recommendations regenerate |
| 隐藏一条采购建议 | finance.recommendations.dismiss | vantage finance recommendations dismiss |
| 查看已隐藏采购建议 | finance.recommendations.dismissed.list | vantage finance recommendations dismissed list |
| 恢复全部已隐藏采购建议 | finance.recommendations.dismissed.clear | vantage finance recommendations dismissed clear |
| 恢复一条已隐藏采购建议 | finance.recommendations.dismissed.restore | vantage finance recommendations dismissed restore |
| 读取资产负债表 | finance.balance_sheet.read | vantage finance balance-sheet read |
| 启动面部历史分析 | face.analyze | vantage face analyze |
| 读取实时人脸状态 | face.live.read | vantage face live read |
| 读取面部历史报告 | face.report.read | vantage face report read |
| 导出面部历史 Excel | face.export | vantage face export |
| 读取面部分析进度 | face.progress.read | vantage face progress read |
| 读取项目进度 | project_progress.read | vantage project-progress read |
| 读取脱敏设置和运行目录 | settings.state.read | vantage settings state read |
| 更新设置和 provider 配置 | settings.update | vantage settings update |
| 打开配置路径（仅发现，不可调用；转可见 UI：设置 → 数据与日志 → 配置/历史/日志 → 打开） | settings.open_path | vantage settings open-path |
| 读取显示语言偏好 | settings.display_language.read | vantage settings display-language read |
| 更新显示语言偏好 | settings.display_language.update | vantage settings display-language update |
| 读取系统区域设置（仅发现，不可调用；转可见 UI：设置 → 通用 → 系统区域设置） | system.locale.read | vantage system locale read |
| 更新窗口标题栏主题（仅发现，不可调用；转可见 UI：设置 → 通用 → 主题） | window.title_bar_theme.update | vantage window title-bar-theme update |
| 读取首次运行引导状态 | onboarding.state.read | vantage onboarding state read |
| 选择旧数据根目录（仅发现，不可调用；转可见 UI：首次运行引导 → 迁移数据 → 选择文件夹） | onboarding.legacy_root.pick | vantage onboarding legacy-root pick |
| 完成首次运行引导 | onboarding.complete | vantage onboarding complete |

## 代码与测试定位

- 目录、schema、可用性和操作元数据：src/services/automation_catalog.py。
- 统一 HTTP/配置客户端：src/services/vantage_client.py。
- CLI 参数、发现、渲染与退出码：src/cli.py；MCP stdio、工具和资源：src/mcp_server.py。
- HTTP 组装入口：src/server.py；按职责划分的路由与适配：src/backend/；独立任务/调度服务：src/services/action_plan_jobs.py 与 action_plan_scheduler.py；设置 JSON 清洗及持久化：src/core/user_config.py；应用与数据目录：src/core/config.py。
- 桌面设置与窄 OS 侧效果：src/webapp/main.cjs、src/webapp/preload.cjs；行动计划 UI 和只读任务观察：src/webapp/src/components/ActionPlan.jsx、src/webapp/src/utils/actionPlanJobs.js、src/webapp/src/utils/actionPlanStream.js。
- 重点测试：tests/test_automation_catalog.py、tests/test_vantage_client.py、tests/test_cli.py、tests/test_mcp_server.py、tests/test_settings_automation_endpoint.py、tests/test_vantage_skill.py；完整操作覆盖由 tests/test_automation_parity.py 负责。

实现功能后根据改动运行 Python 测试、src/webapp 的 lint/test/build 与运行时打包测试。真实安装验收应区分源码测试、构建包、安装后运行；未执行的步骤必须明确写为未验证。
