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
framework_dir = root / 'milkchan' / 'sentientmilk_framework'
custom_tools_dir = root / 'milkchan' / 'custom_tools'

print(f"[SPEC] Assets directory: {assets_dir}")
print(f"[SPEC] Framework directory: {framework_dir}")
print(f"[SPEC] Custom tools directory: {custom_tools_dir}")

# Collect framework files
framework_datas = []
if framework_dir.exists():
    for py_file in framework_dir.rglob('*.py'):
        rel_path = py_file.relative_to(root)
        framework_datas.append((str(py_file), str(rel_path.parent)))
    print(f"[SPEC] Framework files: {len(framework_datas)}")

# Collect custom tools
custom_tools_datas = []
if custom_tools_dir.exists():
    for py_file in custom_tools_dir.rglob('*.py'):
        rel_path = py_file.relative_to(root)
        custom_tools_datas.append((str(py_file), str(rel_path.parent)))
    print(f"[SPEC] Custom tools files: {len(custom_tools_datas)}")

a = Analysis(
    ['milkchan/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Bundle assets (will be extracted to sys._MEIPASS/assets)
        (str(assets_dir), 'assets'),
    ] + framework_datas + custom_tools_datas,
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
        'requests',
        # SentientMilk framework
        'milkchan.sentientmilk_framework',
        'milkchan.sentientmilk_framework.ai',
        'milkchan.sentientmilk_framework.types',
        'milkchan.sentientmilk_framework.exceptions',
        'milkchan.sentientmilk_framework.tools',
        'milkchan.sentientmilk_framework.tools.read',
        'milkchan.sentientmilk_framework.tools.write',
        'milkchan.sentientmilk_framework.tools.edit',
        'milkchan.sentientmilk_framework.tools.delete',
        'milkchan.sentientmilk_framework.tools.exec',
        # Custom tools
        'milkchan.custom_tools',
        'milkchan.custom_tools.update_sprite',
        'milkchan.custom_tools.memory',
        'milkchan.custom_tools.take_screenshot',
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