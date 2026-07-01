@echo off
setlocal

:: Switch to script directory
cd /d "%~dp0"

:: Detect Python
set PYTHON_CMD=
python --version >nul 2>&1 && set PYTHON_CMD=python
if not defined PYTHON_CMD (
    py --version >nul 2>&1 && set PYTHON_CMD=py
)
if not defined PYTHON_CMD (
    python3 --version >nul 2>&1 && set PYTHON_CMD=python3
)

if not defined PYTHON_CMD (
    echo [ERROR] Python not found.
    echo Please install Python from python.org and check "Add Python to PATH".
    pause
    exit /b 1
)

:: Check if core dependencies are importable
echo [1/2] Checking dependencies...
"%PYTHON_CMD%" -c "import PySide6, openai" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing missing dependencies...
    "%PYTHON_CMD%" -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Dependency installation failed.
        echo Try using a mirror: pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
)

:: Run
echo.
echo [2/2] Starting AI EPUB Translator (default mode)...
"%PYTHON_CMD%" main.py

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Program exited with error code: %errorlevel%.
    pause
)
endlocal
