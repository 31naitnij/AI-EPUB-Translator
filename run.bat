@echo off
setlocal
set "VENV_DIR=.venv"

:: 0. Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] 找不到 Python。请先安装 Python 并将其添加到系统 PATH 中。
    pause
    exit /b 1
)

:: 1. Check if venv exists
if not exist "%VENV_DIR%" (
    echo [1/3] 正在创建虚拟环境 (%VENV_DIR%)...
    python -m venv %VENV_DIR%
    if %errorlevel% neq 0 (
        echo [ERROR] 无法创建虚拟环境。
        pause
        exit /b 1
    )
)

:: 2. Install requirements
echo [2/3] 正在检查并安装缺失的依赖...
"%VENV_DIR%\Scripts\pip" install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo [ERROR] 依赖安装失败。请检查网络连接。
    pause
    exit /b 1
)

:: 3. Run
echo.
echo [3/3] 正在启动 AI EPUB Translator...
"%VENV_DIR%\Scripts\python" main.py

if %errorlevel% neq 0 (
    echo.
    echo 程序异常退出，错误码: %errorlevel%。
    pause
)
endlocal
