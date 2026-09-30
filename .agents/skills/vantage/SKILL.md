---
name: vantage
description: Use when operating, configuring, diagnosing, or automating the Vantage desktop app with its CLI, MCP tools, or visible computer use.
---

# Vantage 操作指南

项目记忆在 Vantage 的 docs/vantage-project-memory.md，不在 AGENTS.md 中。需要机器可读结果时可用 --format json；后端状态检查对应 system.status.read。

开始操作前先读 Vantage 仓库内的项目记忆：docs/vantage-project-memory.md。项目记忆保存在 Vantage，不放进 AGENTS.md；它是导航参考，不是当前接口的权威来源。涉及能力、参数或运行状态时以当前代码、测试和实际状态为准。

## 选择正确的入口

- 一次性读取、可复现操作或脚本化任务：优先使用安装版 CLI（vantage）或源码模式（python -m src.cli）。先查看 vantage --help 和目标命令的 --help。
- 由助手直接调用产品能力：优先使用 Vantage MCP；安装版入口是 vantage mcp，源码入口是 python -m src.cli mcp。它通过 stdio 运行，要求 Vantage 后端已运行；如果后端未就绪，提示用户启动 Vantage，不要另外启动一个服务器。
- 需要检查屏幕、可视化结果、原生窗口效果或桌面专属操作时，使用 computer use/可见 Vantage UI。不要把 CLI/MCP 报告的内容误说成已经在屏幕上显示。
- MCP 操作列表来自自动化目录。先列工具或读取 vantage://catalog；需要 schema 时读取对应的 vantage://operations/<operation-name>。准确使用目录中的稳定名称，不要猜测不存在的工具。

## 桌面专属操作的 Computer Use 路径

自动化目录中的 `desktop_only` 操作只可被 CLI/MCP 发现，调用会返回不可用；不要把列出的命令当作可执行替代。需要这些能力时，切到已运行的 Vantage 可见窗口，用 Computer Use 按下面的入口操作，并观察结果：

- `settings.open_path`：设置 → 数据与日志 → 配置/历史/日志 → 打开。验证文件管理器打开了所选路径；仅在用户要求时操作。
- `system.locale.read`：设置 → 通用 → 系统区域设置（只读）。核对该行显示的系统区域值；显示语言“跟随系统”是单独设置，不要混为一谈。
- `window.title_bar_theme.update`：设置 → 通用 → 主题 → 自动/深色/浅色。选择目标项并保存；验证应用主题和原生标题栏外观都已更新。
- `onboarding.legacy_root.pick`：仅在首次运行引导仍显示时，首次运行引导 → 迁移数据 → 选择文件夹。核对已选目录显示正确后再继续；不要擅自确认或执行导入。已完成引导后该系统文件夹选择器没有可重复打开的设置入口，应如实说明。

Computer Use 的屏幕观察和操作结果是桌面效果的验证依据；CLI/MCP 返回值不能证明原生窗口或文件管理器已经显示、更新。

## 安全地读写设置

修改设置前，先调用 settings.state.read，确认当前值；用 settings.update 只提交用户明确要求的最小改动，再调用 settings.state.read 验证返回值确已更新。CLI 对应命令是 vantage settings state read 和 vantage settings update。操作参数以命令帮助或 MCP schema 为准。

涉及结构化值或密钥时优先使用 --input-json - 从标准输入传 JSON，避免将密钥放在命令行参数、shell 历史、日志或答复中。API key 是 write-only，读取结果会脱敏，不尝试从返回值还原。

更新 provider_config 时注意：省略的顶层字段保留原值；一旦提交 providers 字典，它会替换完整 provider 集合。没有用户提供的完整目标配置时，不能把只包含一个 provider 的不完整字典写回。

不要混淆 action_plan_auto_generate 和 action_plan_check_interval_minutes：前者控制后端启动/跨日缺少完整计划时的自动生成条件，后者控制后端是否及多久检查行动计划数据变化；有效范围是 0–35,791 分钟，0 表示关闭轮询。CLI/MCP 修改后由后端调度动态读取；可用 action_plan.scheduler.read 核对运行时状态，无需重载界面。

CLI/MCP 对 settings.update、settings.display_language.update 和 onboarding.complete 的确认仅表示 JSON 持久化成功，不代表登录启动项、托盘标签等 Electron 原生效果已应用。需要这些原生效果时，通过桌面 UI 操作并单独确认。

调用 onboarding.complete 必须明确传入 skip_chat_setup；设为 true 时保留已有 provider 配置，设为 false 时必须传 selected_provider，且只合并所选 provider。不能用 onboarding.complete 替代日常设置更新。
如果启用 import_legacy_data=true，还必须明确传入 legacy_root；只在用户明确要求导入且界面显示所选路径正确后继续。

## 行动计划：等待成功，再验证

手动查询使用 action_plan.today.read；需要生成时使用 action_plan.jobs.create，记录任务ID，再用 action_plan.jobs.events 或 action_plan.jobs.read 观察结果。是否替换今天的保存结果由 replace_today 参数控制，只有用户要求替换时才将其设为 true。

action_plan.jobs.events 返回进度流。必须持续读取到成功完成事件 done=true；如果出现 error、STREAM_ERROR、超时、流提前结束或正文不完整，就按失败处理，不报告计划已替换。成功后重新读取 action_plan.today.read，确认最新日期、分析和计划正文完整，再给用户结论。

定时检查数据变化由后端负责，任何 UI 或 CLI/MCP 通过 settings.update 设置间隔后都共享同一调度。action_plan.source_revision.read 可读取来源指纹，action_plan.scheduler.read 可查看调度状态。长任务使用 action_plan.jobs.create、action_plan.jobs.list、action_plan.jobs.read、action_plan.jobs.events、action_plan.jobs.cancel；断开观察不会取消后端任务，只有显式 cancel 才取消。只有 succeeded 且完整保存结果才算完成；显示效果仍需可见 UI 单独验证。

注意两个有副作用的操作：face.live.read 只有在确实需要标记实时查看器可见时才传 active=true；system.media.open_folder 会打开系统文件管理器，不是纯读取。

## 结果与交接

报告中写清用了哪个操作、改变了什么、如何通过再次读取验证；区分只读检查、已提交修改、运行时已确认和仍未验证事项。若请求超出当前目录能力，说明缺口并改用可见 UI 或征求用户选择。不要把私有数据、提示词、日志、密钥或机器专属路径加入项目文档或提交。
