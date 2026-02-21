@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set "VENV_PYTHON=.venv\Scripts\python.exe"

echo [1/3] Preparing environment...

:: Check pyinstaller
if exist "%VENV_PYTHON%" (
    echo [INFO] Using virtual environment...
    "%VENV_PYTHON%" -m pip install pyinstaller --quiet
    set "CMD_PREFIX="%VENV_PYTHON%" "
) else (
    echo [WARNING] No venv found, using system Python...
    pip install pyinstaller --quiet
    set "CMD_PREFIX=python "
)

echo.
echo [2/3] Building EXE (this may take a few minutes)...
echo Building...

%CMD_PREFIX% build.py

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Build failed! Check messages above.
    pause
    exit /b 1
)

echo.
echo [3/3] Build successful!
echo Check the 'dist' folder.
pause
endlocal
