@echo off
chcp 65001 >nul
reg add "HKCU\Console" /v CodePage /t REG_DWORD /d 65001 /f >nul

:: 切换控制台字体为支持中文的字体（如 Lucida Console）
reg add "HKCU\Console" /v FaceName /t REG_SZ /d "Lucida Console" /f >nul

echo 正在转换图标...
python convert_icon.py
echo 正在打包任务管理器程序...

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo 未检测到 PyInstaller，正在安装...
    pip install pyinstaller
)

pyinstaller --onefile --noconsole --icon=icon.ico --add-data "icon.png;." --distpath . ./src/main.py

echo 打包完成！请在 dist 文件夹中查找 exe 文件。
pause
