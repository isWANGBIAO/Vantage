# Vantage

Vantage 现在有两种使用方式：

- 正式使用：安装 Windows 安装包。
- 开发调试：在仓库根目录运行 `RUN.bat`。

## 正式使用

- 安装包输出路径：`src/webapp/electron-dist/Vantage Setup 1.0.0.exe`
- 双击安装包后，按安装向导完成安装即可使用。
- 安装后会创建开始菜单和桌面快捷方式。
- 首次启动进入引导配置。
- 聊天配置可以当场完成，也可以先跳过。
- 用户数据统一保存在 `%LOCALAPPDATA%\Vantage`。
- 覆盖安装会保留历史、配置、日志和运行数据。
- 卸载程序时，默认不会删除 `%LOCALAPPDATA%\Vantage` 下的用户数据。

## 开发使用

所有开发命令都从仓库根目录运行。

### 启动开发环境

```bat
RUN.bat
```

### 构建后端 runtime

```bat
python src/scripts/build_backend_runtime.py
```

### 校验后端 runtime

```bat
python src/scripts/verify_backend_runtime.py --timeout-seconds 60
```

### 构建 Windows 安装包

```bat
cd src/webapp
npm run electron:build
```

## 目录约定

- 安装目录：程序文件和内置 runtime，只读使用。
- 用户数据目录：`%LOCALAPPDATA%\Vantage`
- 配置目录：`%LOCALAPPDATA%\Vantage\config`
- 历史目录：`%LOCALAPPDATA%\Vantage\history`
- 日志目录：`%LOCALAPPDATA%\Vantage\logs`
- 图表输出目录：`%LOCALAPPDATA%\Vantage\plot_outputs`

## 说明

- `RUN.bat` 保留为开发和回退入口，不再作为正式交付入口。
- 安装包模式下不要求用户预装 Python、Node、npm 或 CUDA。
