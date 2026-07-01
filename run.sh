#!/bin/bash

# Switch to script directory
cd "$(dirname "$0")" || exit 1

# Detect Python
PYTHON_CMD=""
python3 --version >/dev/null 2>&1 && PYTHON_CMD=python3
if [ -z "$PYTHON_CMD" ]; then
    python --version >/dev/null 2>&1 && PYTHON_CMD=python
fi
if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python not found."
    exit 1
fi

# Check if core dependencies are importable
echo "[1/2] Checking dependencies..."
"$PYTHON_CMD" -c "import PySide6, openai" >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "[INFO] Installing missing dependencies..."
    "$PYTHON_CMD" -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[ERROR] Dependency installation failed."
        echo "Try: pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
        exit 1
    fi
fi

# Run
echo ""
echo "[2/2] Starting AI EPUB Translator (default mode)..."
"$PYTHON_CMD" main.py

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "[WARNING] Program exited with error code: $EXIT_CODE"
fi
