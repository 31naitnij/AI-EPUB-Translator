# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['src', 'src.config', 'src.core', 'src.core.cache_manager', 'src.core.config_manager', 'src.core.converter', 'src.core.epub_manager', 'src.core.parser', 'src.core.processor', 'src.core.translator', 'src.core.worker', 'src.core.document_converter', 'src.core.converter_factory', 'src.core.document_manager', 'src.core.converters', 'src.core.converters.epub_converter', 'src.core.converters.docx_converter', 'src.core.converters.doc_converter', 'src.core.converters.pdf_converter', 'src.ui', 'src.ui.main_window', 'src.ui.settings_widget', 'src.ui.file_widget', 'src.ui.monitor_widget', 'docx', 'fitz', 'reportlab', 'reportlab.pdfgen', 'reportlab.lib', 'reportlab.platypus']
tmp_ret = collect_all('reportlab')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='AI_Document_Translator',
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
