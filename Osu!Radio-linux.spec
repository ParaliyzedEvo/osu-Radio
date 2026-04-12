# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, Tree

tree_datas = Tree('lazer/dist', prefix='.')
hiddenimports = collect_submodules('pynput') + ['simplejson']

a = Analysis(
    ['osuRadio//main.py'],
    pathex=[],
    binaries=[('dist/updater','.'),('lazer/dist/lazer','.')],
    datas=[('osuRadio/Background Video', 'Background Video'),('osuRadio/Osu!RadioIcon.ico','.'),('osuRadio/ffmpeg_bin','ffmpeg_bin'),('osuRadio/img','img')] + tree_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
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
	icon="osuRadio/Osu!RadioIcon.png"
)