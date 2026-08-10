# PyInstaller spec — built on windows-latest CI, not locally.
# Run with: pyinstaller build.spec
import imageio_ffmpeg

block_cipher = None

ffmpeg_binary = imageio_ffmpeg.get_ffmpeg_exe()

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[(ffmpeg_binary, '.')],
    datas=[],
    hiddenimports=[
        'scenedetect',
        'scenedetect.detectors',
        'scipy.signal',
        'scipy.special._cdflib',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TiktokAutoEdit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TiktokAutoEdit',
)
