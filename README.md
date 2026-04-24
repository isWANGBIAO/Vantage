# Vantage

Vantage 现在分成两个明确入口：

- 正式发布与本机覆盖安装：在仓库根目录运行 `RUN.bat`
- 源码开发调试：在仓库根目录运行 `RUN_DEV.bat`

## 正式发布使用

`RUN.bat` 现在会顺序执行这些步骤：

1. 清理当前仓库残留的源码进程
2. 构建后端 runtime
3. 校验后端 runtime
4. 构建 Windows NSIS 安装包
5. 删除启动文件夹里旧的 `RUN.bat` 快捷方式残留
6. 静默安装最新安装包
7. 自动启动安装后的 `Vantage.exe`

安装包输出目录仍然是：

`src/webapp/electron-dist`

当前安装包文件名示例：

`src/webapp/electron-dist/Vantage Setup 1.0.0.exe`

安装后会创建开始菜单和桌面快捷方式。首次启动进入引导配置。覆盖安装会保留 `%LOCALAPPDATA%\Vantage` 下的历史、配置、日志和运行数据。

## 开发使用

所有开发命令都从仓库根目录运行。

### 启动源码开发环境

```bat
RUN_DEV.bat
```

### 单独构建后端 runtime

```bat
python src/scripts/build_backend_runtime.py
```

### 单独校验后端 runtime

```bat
python src/scripts/verify_backend_runtime.py --timeout-seconds 60
```

### 单独构建 Windows 安装包

```bat
npm --prefix src/webapp run electron:build
```

## 目录约定

- 安装目录：程序文件和内置 runtime，只读使用
- 用户数据目录：`%LOCALAPPDATA%\Vantage`
- 配置目录：`%LOCALAPPDATA%\Vantage\config`
- 历史目录：`%LOCALAPPDATA%\Vantage\history`
- 日志目录：`%LOCALAPPDATA%\Vantage\logs`
- 图表输出目录：`%LOCALAPPDATA%\Vantage\plot_outputs`

## 说明

- `RUN.bat` 现在是发布和本机覆盖安装入口，不再承担源码开发启动职责
- `RUN_DEV.bat` 是新的开发和回退入口
- 安装包模式下不要求用户预装 Python、Node、npm 或 CUDA
