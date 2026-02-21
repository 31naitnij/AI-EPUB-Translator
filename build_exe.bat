@echo off
echo [1/3] 正在安装 PyInstaller...
pip install pyinstaller

echo.
echo [2/3] 正在生成单文件可执行程序 (EXE)...
echo 这可能需要几分钟时间，请稍候...

python build.py

echo.
echo [3/3] 构建完成！
echo EXE 文件位于 dist 文件夹下。
pause
