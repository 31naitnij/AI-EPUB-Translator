# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# Collect all submodules from project's own packages (PyInstaller may miss
# dynamically imported modules like processor_direct)
hiddenimports += collect_submodules('src')

# Collect dependencies for openai SDK (has dynamic submodules)
for pkg in ['openai']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

# PySide6: PyInstaller 6.x has built-in hooks that auto-detect used modules.
# We do NOT collect_all('PySide6') because it pulls in 200MB+ of unused Qt modules.
# The built-in hook handles QtWidgets/QtCore/QtGui correctly.

# Explicitly exclude unused libraries (also removed from requirements.txt)
excludes = [
    'markdown', 'lxml', 'ebooklib', 'beautifulsoup4', 'bs4',
    'QtWebEngine', 'QtWebEngineCore', 'QtWebEngineWidgets',
    'QtMultimedia', 'QtMultimediaWidgets',
    'QtQuick', 'QtQml', 'QtTest', 'QtSql', 'Qt3D',
    'QtCharts', 'QtDataVisualization', 'QtBluetooth',
    'QtNfc', 'QtPositioning', 'QtSensors', 'QtRemoteObjects',
]

a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EPUB_Translator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
