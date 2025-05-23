# -*- mode: python ; coding: utf-8 -*-
import os
app_name = 'osuRadio'
main_script = 'Osu!Radio.py'
project_root = os.getcwd()

a = Analysis(
    [main_script],
    pathex=[],
    binaries=[],
    datas=[('Background Video', 'Background Video')],
    hiddenimports=[],
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
    [],
    exclude_binaries=False,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name=app_name
)