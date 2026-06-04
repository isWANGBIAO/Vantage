# Vantage

Vantage 现在支持 Windows 和 macOS 两个桌面系统。程序启动后，后端会按 60 秒周期进行一次照片采集与截图采集；摄像头后端、通知和打包产物会按当前系统自动选择。

入口分成正式安装和源码开发两类：

- Windows 正式发布与本机覆盖安装：在仓库根目录运行 `RUN.bat`
- Windows 源码开发调试：在仓库根目录运行 `RUN_DEV.bat`
- macOS 正式发布与本机覆盖安装：在仓库根目录运行 `./RUN.sh`
- macOS 源码开发调试：在仓库根目录运行 `./RUN_DEV.sh`

## 正式发布使用

### Windows

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

### macOS

`RUN.sh` 会顺序执行这些步骤：

1. 清理当前仓库残留的源码进程
2. 检查前端依赖
3. 准备后端 runtime 打包虚拟环境
4. 构建前端和后端 runtime
5. 校验后端 runtime
6. 构建 macOS Electron app 包
7. 覆盖安装到 `~/Applications/Vantage.app`
8. 自动启动安装后的 `Vantage.app`

首次启动需要授予摄像头和屏幕录制权限；没有定位权限或平台定位不可用时，图片仍会保存，只是不写入 GPS EXIF。

## 开发使用

所有开发命令都从仓库根目录运行。

### 启动源码开发环境

```bat
RUN_DEV.bat
```

macOS：

```bash
./RUN_DEV.sh
```

### 单独构建后端 runtime

```bat
python src/scripts/build_backend_runtime.py
```

### 单独校验后端 runtime

```bat
python src/scripts/verify_backend_runtime.py --timeout-seconds 60
```

### 单独构建当前系统安装包

```bash
npm --prefix src/webapp run electron:build
```

## 目录约定

- 安装目录：程序文件和内置 runtime，只读使用
- 用户数据目录：`%LOCALAPPDATA%\Vantage`
- 配置目录：`%LOCALAPPDATA%\Vantage\config`
- 历史目录：`%LOCALAPPDATA%\Vantage\history`
- 日志目录：`%LOCALAPPDATA%\Vantage\logs`
- 图表输出目录：`%LOCALAPPDATA%\Vantage\plot_outputs`

macOS 打包模式使用系统标准目录：

- 用户数据目录：`~/Library/Application Support/Vantage`
- 配置目录：`~/Library/Application Support/Vantage/config`
- 历史目录：`~/Library/Application Support/Vantage/history`
- 日志目录：`~/Library/Application Support/Vantage/logs`
- 图表输出目录：`~/Library/Application Support/Vantage/plot_outputs`

## 说明

- `RUN.bat` / `RUN.sh` 是发布和本机覆盖安装入口，不再承担源码开发启动职责
- `RUN_DEV.bat` / `RUN_DEV.sh` 是开发和回退入口
- 安装包模式下不要求用户预装 Python、Node、npm 或 CUDA
- 大模型密钥应写入运行时配置或 `.env`，不要提交到 Git。运行时配置目录 `config/` 已被 `.gitignore` 忽略。
