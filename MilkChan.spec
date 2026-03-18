# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for MilkChan
Builds single executable with bundled assets
"""

import sys
import os
from pathlib import Path

# Project root
root = Path(SPECPATH)

# Collect all assets
assets_dir = root / 'milkchan' / 'desktop' / 'assets'

print(f"[SPEC] Assets directory: {assets_dir}")
print(f"[SPEC] Assets exists: {assets_dir.exists()}")
if assets_dir.exists():
    print(f"[SPEC] Assets contents: {list(assets_dir.iterdir())}")

a = Analysis(
    ['milkchan/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Bundle assets (will be extracted to sys._MEIPASS/assets)
        (str(assets_dir), 'assets'),
    ],
    hiddenimports=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PIL',
        'PIL.Image',
        'numpy',
        'openai',
        'sqlite3',
        'dotenv',
        'scipy',
        'scipy.io',
        'scipy.io.wavfile',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        'milkchan/pyi_rth_qt.py',
    ],
    excludes=[
        'tkinter',
        'matplotlib',
        'pandas',
        'IPython',
        'jupyter',
    ],
    noarchive=False,
    optimize=1,
)

print(f"[SPEC] Analysis datas: {len(a.datas)} entries")
for d in a.datas[:5]:
    print(f"[SPEC]   - {d}")

# Filter out OpenCV's Qt plugins on Linux (they conflict with PyQt5)
if sys.platform.startswith('linux'):
    filtered_binaries = []
    for binary in a.binaries:
        if 'cv2/qt/plugins' not in str(binary[0]):
            filtered_binaries.append(binary)
    a.binaries = filtered_binaries

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MilkChan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set False for release, True for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(assets_dir / 'icon.ico')],
)