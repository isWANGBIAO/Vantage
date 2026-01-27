@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo    AI Manager - Electron 启动脚本
echo ========================================
echo.

:: 获取脚本所在目录（项目根目录）
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

:: 检查 Python 后端
echo [1/3] 检查后端服务...

:: 检查端口 8000 是否被占用
netstat -an | find ":8000" | find "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo       发现后端服务正在运行，正在重启以加载最新代码...
    :: 结束现有的 Python 进程 (server.py)
    for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do (
        taskkill /f /pid %%a >nul 2>&1
    )
    timeout /t 1 /nobreak >nul
)

echo       启动 FastAPI 后端...
if not exist "%PROJECT_ROOT%logs" mkdir "%PROJECT_ROOT%logs"
start "AI Manager Backend" /min cmd /c "cd /d %PROJECT_ROOT% && python src/server.py > logs/server.log 2>&1"

:: 等待后端启动
echo       等待后端就绪...
timeout /t 3 /nobreak >nul

:: 检查 node_modules
echo [2/3] 检查依赖...
if not exist "%PROJECT_ROOT%src\webapp\node_modules" (
    echo       安装依赖中...
    cd /d "%PROJECT_ROOT%src\webapp"
    call npm install
) else (
    echo       依赖已安装
)

:: 启动 Electron
echo [3/3] 启动 Electron 应用...
cd /d "%PROJECT_ROOT%src\webapp"

:: 检查是使用开发模式还是生产模式
if exist "%PROJECT_ROOT%src\webapp\dist\index.html" (
    echo       使用生产模式...
    call npm run electron:start
) else (
    echo       使用开发模式...
    call npm run electron:dev
)

echo.
echo ========================================
echo    应用已关闭
echo ========================================
pause
