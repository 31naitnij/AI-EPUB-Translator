@echo off
setlocal enabledelayedexpansion
set "VENV_DIR=.venv"

echo [0/3] 正在检查 Python 环境...

:: 简化 Python 检测逻辑
set PYTHON_CMD=
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
) else (
    py --version >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_CMD=py
    ) else (
        python3 --version >nul 2>&1
        if !errorlevel! equ 0 (
            set PYTHON_CMD=python3
        )
    )
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] 在您的系统中找不到 Python。
    echo 请前往 python.org 安装 Python，并确保安装时勾选了 "Add Python to PATH"。
    pause
    exit /b 1
)

echo [DEBUG] 使用指令: %PYTHON_CMD%

:: 1. 创建虚拟环境
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/3] 正在创建虚拟环境 %VENV_DIR%...
    %PYTHON_CMD% -m venv %VENV_DIR%
    if !errorlevel! neq 0 (
        echo [ERROR] 无法创建虚拟环境。
        pause
        exit /b 1
    )
)

:: 2. 安装依赖
echo [2/3] 正在检查并安装缺失的依赖...
"%VENV_DIR%\Scripts\python" -m pip install --upgrade pip --quiet
"%VENV_DIR%\Scripts\pip" install -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] 依赖安装失败。
    pause
    exit /b 1
)

:: 3. 运行程序
echo.
echo [3/3] 正在启动 AI EPUB Translator...
"%VENV_DIR%\Scripts\python" main.py

if !errorlevel! neq 0 (
    echo.
    echo [WARNING] 程序异常退出，错误码: !errorlevel!。
    pause
)
endlocal
