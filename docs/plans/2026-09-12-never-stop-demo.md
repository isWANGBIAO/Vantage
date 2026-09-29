# Never Stop Demo Implementation Plan

**Goal:** 实现一个独立桌面入口，让用户持续调用已配置的 Claude Code / Codex，以播放、暂停、发布目标和重置上下文控制项目。

**Architecture:** 复用现有 Electron、React、Markdown 和图表依赖；独立 `src/webapp/never-stop` 入口。Electron 主进程作为窗口之外的本地运行器，关闭窗口保留托盘；每个规范化目录一个顶层执行进程。用户意图和已发布目标存于应用数据目录，项目只保存草稿及进度协议文件。

**Tech Stack:** Node.js、Electron、React、Vite、ECharts、Node test runner。

## 已确定设计

- 以最终开发要求为准，设计已获直接执行授权。隔离 Demo 优于替换 Vantage 主页面；无需新增 Python 服务或公网通信。
- 正常退出立即续跑，快速失败可取消节流，无最终重试次数；只有用户控制能停止循环。先保存控制意图，再结束受管理进程树。
- 明确会话 ID 续接；发布中断后重用会话，重置中断后新建会话。保留 Agent 自身权限与模型配置。
- `goal.md` 自动保存仅更新草稿，显式发布更新应用快照。并发修改通过内容版本检测，冲突交由用户处理。
- `.never-stop/progress.json` 为 Agent 自评最新快照，程序只验证显示协议，生成 `progress.md`；错误保留最后有效数据。
- 凭据用平台加密能力保存，经本地辅助入口取用；普通提示词和日志不含明文秘密。
- 不实现业务验收、科研评分、自动提交、强模型调度或多 Agent 产品编排。

## 实施与验证

1. **运行器与适配器**：`core/runner.cjs`、`core/adapters.cjs`、`core/process-owner.cjs`。先写假 CLI 测试，验证多项目、真实 cwd、十次失败仍恢复、100% 不停止、暂停无复活、发布与重置串行、进程所有权与重启恢复，再实现。
2. **文件协议**：`core/files.cjs` 及测试。验证草稿冲突、不发布不切换、非法及半写 JSON 保留上次快照、首次快照前保留已有 progress.md、范围和类型严格验证。
3. **桌面辅助**：`core/resources.cjs`、`discovery.cjs`、`notifications.cjs` 及测试。验证加密存储、可实际使用的本地凭据入口、只读项目发现及失败提示、当地时间通知去重。
4. **UI**：`ui/` 独立页面和交互测试。雷达图居中、目标与进度抽屉、冲突处理、键盘焦点规则、资源及提醒设置；构建并实际启动验证。
5. **集成**：独立 Electron main/preload、启动 BAT、专用构建配置。验证关闭窗口继续、重开单实例复用、原生通知、真实 CLI 临时目录最小接入。
6. **交付**：执行 Demo 测试、现有前端测试及构建，审查控制竞态和凭据边界；记录实际已测/未测平台，提供源码、启动说明和最小 Vantage 接入点，详细本地提交。

## 开发事实来源

开发时同时核验本机 CLI 帮助与官方文档，避免将内部存储格式当作稳定 API。

- https://code.claude.com/docs/en/cli-reference
- https://developers.openai.com/codex/noninteractive

附件只包含执行原则文件名，没有该配套文件全文；实现根据附件明确原则整理版本化 v0.1 模板，并在交付说明中注明。
