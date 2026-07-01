#!/bin/bash

# 确保脚本在出错时停止
set -e

# 切换到脚本所在目录 (确保从任意目录调用时 CWD 正确)
cd "$(dirname "$0")" || exit 1

VENV_DIR=".venv"

# 1. 确保使用虚拟环境 (与 run.sh 保持一致)
if [ ! -d "$VENV_DIR" ]; then
    echo "[0/3] 创建虚拟环境 ($VENV_DIR)..."
    python3 -m venv "$VENV_DIR"
fi

echo "[1/3] 正在安装 PyInstaller..."
"$VENV_DIR/bin/pip" install pyinstaller --quiet --disable-pip-version-check

echo ""
echo "[2/3] 正在生成 macOS 可执行文件..."
echo "这可能需要几分钟时间，请稍候..."

"$VENV_DIR/bin/python3" build.py

echo ""
echo "[3/3] 构建完成！"
echo "应用程序位于 dist 文件夹下 (AI_EPUB_Translator.app 或 AI_EPUB_Translator 可执行文件)。"
echo "注意：在 macOS 上，通常会生成一个 .app 包。"
