# -*- mode: python ; coding: utf-8 -*-
app_name = 'osu!Radio'
main_script = 'osu!Radio//main.py'

a = Analysis(
    [main_script],
    pathex=[],
    binaries=[('dist/updater.exe','.')],
    datas=[('osu!Radio/Background Video', 'Background Video'),('osu!Radio/Osu!RadioIcon.ico','.'),('osu!Radio/ffmpeg_bin','ffmpeg_bin')],
    hiddenimports=['simplejson'],
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
    name='osu!Radio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='osu!Radio/Osu!RadioIcon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='osu!Radio'
)