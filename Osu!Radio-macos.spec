# -*- mode: python ; coding: utf-8 -*-
app_name = 'osu!Radio'
main_script = 'Osu!Radio.py'

a = Analysis(
    [main_script],
    pathex=[],
    binaries=[],
    datas=[('Background Video', 'Background Video'),('Osu!RadioIcon.ico','.'),('ffmpeg_bin','ffmpeg_bin')],
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
    icon='Osu!RadioIcon.icns',
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