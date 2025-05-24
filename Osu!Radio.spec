# -*- mode: python ; coding: utf-8 -*-

import sys
import os

app_name = 'Osu!Radio'
main_script = 'Osu!Radio.py'

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
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,  # Important for macOS GUI apps
    icon=['Osu!RadioIcon.icns'],  # Use `.icns` for macOS
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

app = BUNDLE(
    exe,
    name=app_name + '.app',
    icon=None,
    bundle_identifier='com.yourdomain.osuradio',  # Customize this
    info_plist={
        'CFBundleName': app_name,
        'CFBundleDisplayName': app_name,
        'CFBundleIdentifier': 'com.yourdomain.osuradio',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': 'True',
    }
)

coll = COLLECT(
	exe,
    app,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)