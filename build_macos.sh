#!/bin/bash

# 确保脚本在出错时停止
set -e

echo "[1/3] 正在安装 PyInstaller..."
python3 -m pip install pyinstaller

echo ""
echo "[2/3] 正在生成 macOS 可执行文件..."
echo "这可能需要几分钟时间，请稍候..."

python3 build.py

echo ""
echo "[3/3] 构建完成！"
echo "应用程序位于 dist 文件夹下 (AI_EPUB_Translator.app 或 AI_EPUB_Translator 可执行文件)。"
echo "注意：在 macOS 上，通常会生成一个 .app 包。"
read -p "按任意键确认..."
