@echo off
chcp 65001 >nul
reg add "HKCU\Console" /v CodePage /t REG_DWORD /d 65001 /f >nul

:: 切换控制台字体为支持中文的字体（如 Lucida Console）
reg add "HKCU\Console" /v FaceName /t REG_SZ /d "Lucida Console" /f >nul

echo 正在转换图标...
python convert_icon.py
echo 正在打包任务管理器程序...

:: 记录开始时间
set "start_time=%time%"

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo 未检测到 PyInstaller，正在安装...
    pip install pyinstaller
)

pyinstaller --onefile --noconsole --icon=icon.ico --add-data "icon.png;." --distpath . --exclude PyQt5 ./src/main.py
@REM pyinstaller --onedir --noconsole --icon=icon.ico --add-data "icon.png;." --distpath ./dist ./src/main.py


:: 记录结束时间
set "end_time=%time%"

:: 计算时间差
for /f "tokens=1-4 delims=:.," %%a in ("%start_time%") do (
    set /a "start_seconds=(((%%a*60)+%%b)*60+%%c)*100+%%d"
)
for /f "tokens=1-4 delims=:.," %%a in ("%end_time%") do (
    set /a "end_seconds=(((%%a*60)+%%b)*60+%%c)*100+%%d"
)

set /a "elapsed_time_ms=end_seconds - start_seconds"
if %elapsed_time_ms% lss 0 set /a "elapsed_time_ms += 8640000"  :: 跨越午夜的处理

set /a "elapsed_sec=elapsed_time_ms / 100"
set /a "elapsed_ms=elapsed_time_ms %% 100"

echo 打包完成！用时 %elapsed_sec%.%elapsed_ms% 秒。
pause
