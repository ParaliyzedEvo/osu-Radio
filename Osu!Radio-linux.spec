# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('pynput') + ['simplejson']

a = Analysis(
    ['osu!Radio//main.py'],
    pathex=[],
    binaries=[('dist/updater','.')],
    datas=[('osu!Radio/Background Video', 'Background Video'),('osu!Radio/Osu!RadioIcon.ico','.'),('osu!Radio/ffmpeg_bin','ffmpeg_bin')],
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
    name='osu!Radio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
	icon="osu!Radio/Osu!RadioIcon.png"
)