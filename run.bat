@echo off
set "VENV_DIR=.venv"

:: 1. Check if venv exists
if not exist "%VENV_DIR%" (
    echo [1/3] Creating virtual environment...
    python -m venv %VENV_DIR%
)

:: 2. Install requirements
echo [2/3] Checking dependencies...
"%VENV_DIR%\Scripts\pip" install -r requirements.txt --quiet --disable-pip-version-check

:: 3. Run
echo.
echo [3/3] Starting AI EPUB Translator...
"%VENV_DIR%\Scripts\python" main.py

if %errorlevel% neq 0 (
    echo.
    echo Program exited with error code %errorlevel%.
    pause
)
