# -*- mode: python ; coding: utf-8 -*-
app_name = 'osu!Radio'
main_script = 'osu!Radio//main.py'

a = Analysis(
    [main_script],
    pathex=[],
    binaries=[],
    datas=[('osu!Radio/Background Video', 'Background Video'),('osu!Radio/Osu!RadioIcon.ico','.'),('osu!Radio/ffmpeg_bin','ffmpeg_bin'),('osu!Radio/img','img')],
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
    exclude_binaries=True,
    name='osu!Radio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='Osu!RadioIcon.icns',
)

app = BUNDLE(
    exe,
    name='osu!Radio' + '.app',
    icon='osu!Radio/Osu!RadioIcon.icns',
    bundle_identifier='com.paraliyzedevo.osuradio',
    info_plist={
        'CFBundleName': 'osu!Radio',
        'CFBundleDisplayName': 'osu!Radio',
        'CFBundleIdentifier': 'com.paraliyzedevo.osuradio',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': 'True',
    },
)