# PyInstaller spec — built on windows-latest CI, not locally.
# Run with: pyinstaller build.spec
import imageio_ffmpeg
from PyInstaller.utils.hooks import collect_all

block_cipher = None

ffmpeg_binary = imageio_ffmpeg.get_ffmpeg_exe()

datas = [
    ('app/assets/icon.png', 'app/assets'),
    ('app/assets/face_detection_yunet.onnx', 'app/assets'),
]
binaries = []
hiddenimports = [
    'scenedetect',
    'scenedetect.detectors',
    'scipy.signal',
    'scipy.special._cdflib',
]

# None of these packages (faster-whisper's Whisper models, CTranslate2's
# inference runtime, and its VAD/tokenizer/download dependencies) ship a
# dedicated PyInstaller hook, so collect_all() is used to pull in their
# package data (e.g. faster_whisper's bundled silero_vad_v6.onnx), native
# binaries, and dynamically-imported submodules that PyInstaller's static
# analysis alone would miss. Verified locally that collect_all() resolves
# cleanly for each; the actual Windows-built .exe launching with the
# transcript feature enabled still needs a real end-to-end check on CI.
for _pkg in ('ctranslate2', 'faster_whisper', 'onnxruntime', 'tokenizers', 'huggingface_hub', 'av'):
    _datas, _binaries, _hiddenimports = collect_all(_pkg)
    datas += _datas
    binaries += _binaries
    hiddenimports += _hiddenimports

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[(ffmpeg_binary, '.')] + binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    icon='app/assets/icon.ico',
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
