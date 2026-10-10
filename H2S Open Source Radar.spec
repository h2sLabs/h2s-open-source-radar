# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project = Path(SPECPATH)

a = Analysis(
    ['app.py'],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(project / 'assets' / 'h2s-app-icon.png'), 'assets'),
        (str(project / 'assets' / 'h2s-radar-mark.png'), 'assets'),
    ],
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
    name='H2S Open Source Radar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='H2S Open Source Radar',
)

app = BUNDLE(
    coll,
    name='H2S Open Source Radar.app',
    icon=str(project / 'assets' / 'H2SOpenSourceRadarV2.icns'),
    bundle_identifier='com.h2sstudio.opensource-radar',
    info_plist={
        'CFBundleDisplayName': 'H2S Open Source Radar',
        'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '2',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '13.0',
    },
)
