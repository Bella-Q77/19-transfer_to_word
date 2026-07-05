@echo off
chcp 65001 >nul
echo ============================================
echo   音视频对话转文字工具 - 安装与启动
echo ============================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查 ffmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [警告] 未检测到 ffmpeg，视频文件处理需要 ffmpeg
    echo 下载地址: https://ffmpeg.org/download.html
    echo 请下载后将 ffmpeg.exe 所在目录添加到系统 PATH
    echo.
)

REM 安装依赖
echo [1/2] 正在安装依赖包（首次运行需要下载，请耐心等待）...
pip install -r requirements.txt -q

echo.
echo [2/2] 正在启动工具...
echo.
python audio_to_text.py

pause
