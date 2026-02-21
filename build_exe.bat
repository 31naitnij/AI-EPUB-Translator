@echo off
setlocal
chcp 65001 >nul

:: Set Python path safely
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

echo [1/3] Preparing PyInstaller...
"%PYTHON_EXE%" -m pip install pyinstaller --quiet

echo [2/3] Building EXE...
"%PYTHON_EXE%" build.py

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Build failed.
    pause
    exit /b %ERRORLEVEL%
)

echo [3/3] Done. Check 'dist' folder.
pause
endlocal
