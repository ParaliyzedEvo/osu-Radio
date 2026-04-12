# -*- mode: python ; coding: utf-8 -*-
app_name = 'osu!Radio'
main_script = 'osuRadio//main.py'

from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    [main_script],
    pathex=[],
    binaries=[('dist/updater.exe','.')],
    datas=collect_data_files('lazer/dist') + [('osuRadio/Background Video', 'Background Video'),('osuRadio/Osu!RadioIcon.ico','.'),('osuRadio/ffmpeg_bin','ffmpeg_bin'),('osuRadio/img','img')],
    hiddenimports=['simplejson'],
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
    icon='osuRadio/Osu!RadioIcon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='osu!Radio'
)