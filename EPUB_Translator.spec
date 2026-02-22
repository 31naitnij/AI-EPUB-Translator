# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['src']

# Collect dependencies for markdown, lxml, and ebooklib
for pkg in ['markdown', 'lxml', 'ebooklib']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

# DO NOT collect_all('PySide6') - it includes too much (200MB+)
# PyInstaller will automatically detect used PySide6 modules from imports.

a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'QtWebEngine', 'QtWebEngineCore', 'QtWebEngineWidgets',
        'QtMultimedia', 'QtMultimediaWidgets',
        'QtQuick', 'QtQml', 'QtTest', 'QtSql', 'Qt3D',
        'QtCharts', 'QtDataVisualization', 'QtBluetooth',
        'QtNfc', 'QtPositioning', 'QtSensors', 'QtRemoteObjects'
    ],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
