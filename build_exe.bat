@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set "VENV_PYTHON=.venv\Scripts\python.exe"

echo [1/3] 正在准备构建环境...

:: 检查 pyinstaller
if exist "%VENV_PYTHON%" (
    echo [INFO] 使用虚拟环境 Python 进行构建...
    "%VENV_PYTHON%" -m pip install pyinstaller --quiet
    set "CMD_PREFIX="%VENV_PYTHON%" "
) else (
    echo [WARNING] 未发现虚拟环境，尝试使用系统 Python...
    pip install pyinstaller --quiet
    set "CMD_PREFIX=python "
)

echo.
echo [2/3] 正在生成单文件可执行程序 (EXE)...
echo 这可能需要几分钟时间，请稍候...

%CMD_PREFIX% build.py

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] 构建失败，请检查上方报错信息。
    pause
    exit /b 1
)

echo.
echo [3/3] 构建完成！
echo EXE 文件位于 dist 文件夹下。
pause
endlocal
