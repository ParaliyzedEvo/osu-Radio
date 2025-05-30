# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['Osu!Radio.py'],
    pathex=[],
    binaries=[],
    datas=[('Background Video', 'Background Video'),('Osu!RadioIcon.ico','.')],
    hiddenimports=collect_submodules('pynput'),
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
    name='osu!Radio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
	icon="Osu!RadioIcon.png"
)