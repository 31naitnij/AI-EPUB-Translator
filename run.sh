#!/bin/bash
set -e

VENV_DIR=".venv"

# 1. Check/Create venv
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/3] Creating virtual environment ($VENV_DIR)..."
    python3 -m venv "$VENV_DIR"
fi

# 2. Install dependencies
echo "[2/3] Checking dependencies..."
"$VENV_DIR/bin/pip" install -r requirements.txt --quiet --disable-pip-version-check

# 3. Run
echo ""
echo "[3/3] Starting AI EPUB Translator..."
"$VENV_DIR/bin/python3" main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "Program exited with error."
    read -p "Press any key to exit..."
fi
