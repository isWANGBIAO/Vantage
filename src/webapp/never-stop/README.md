# Never Stop：Vantage 内置页面

Never Stop 现在是 Vantage 左侧导航中的一个页面，共用 Vantage 的 Electron 主进程、窗口、托盘、安装包和版本号，不再单独启动或发布。关闭主窗口只会隐藏到托盘，受管理任务仍继续；从托盘“退出”会先停止受管理进程，保存继续运行意图，下一次启动时再恢复。

首次启动新版 Vantage 时，若旧版 `VantageNeverStop` 用户数据存在且新版数据目录尚不存在，程序会在锁住旧运行器后复制数据、校验文件内容，再启用新版运行器。旧版的 `NEVER_STOP_DATA_DIR` 自定义路径也会作为迁移来源。原数据目录保留作备份；若旧版进程仍在运行，页面会报告错误，不会同时控制同一批项目。若新版目标目录已有另一份数据，程序会明确报冲突，保留两份数据与旧自启动项，不会擅自覆盖或合并。Windows 打包版仅在确认旧数据已迁入后清除旧版专用登录自启项；Vantage 自身的登录自启设置不受影响。原独立版的自动启动偏好不会自动打开 Vantage 的自启动，请在 Vantage 设置中确认。

页面可管理项目、草稿与已发布目标、执行原则、进度、实时输出、资源和通知。所需 Claude Code / Codex CLI、账号及权限仍由用户自行配置；Vantage 不代替它们安装模型，也不会绕过工具权限。项目移除只删应用记录，不删项目文件。

开发验证从仓库根目录运行：

```powershell
npm --prefix src/webapp test
npm --prefix src/webapp run never-stop:test
npm --prefix src/webapp run lint
npm --prefix src/webapp run build
```

`never-stop/core/` 是页面后台业务逻辑；`ui/` 是嵌入的 React 界面。原独立版的交付验证留在 [VALIDATION.md](VALIDATION.md) 作为历史记录，不代表新版集成后的实际验证结果。
