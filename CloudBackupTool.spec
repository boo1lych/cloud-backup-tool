# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

# Файлы тем для sv_ttk (.tcl-файлы стилей) — критично для отображения темы
sv_ttk_datas = collect_data_files('sv_ttk')

a = Analysis(
    ['CloudBackupTool.py'], 
    pathex=[],
    binaries=[],
    datas=[('backup.ico', '.')] + sv_ttk_datas,
    hiddenimports=['psutil'],
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
    name='CloudBackupTool',  
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
    icon=['backup.ico'],
)