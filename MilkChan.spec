# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for MilkChan
Builds single executable with bundled assets
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

# Project root
root = Path(SPECPATH)

# Collect all assets
assets_dir = root / 'milkchan' / 'desktop' / 'assets'
framework_dir = root / 'milkchan' / 'sentientmilk_framework'
custom_tools_dir = root / 'milkchan' / 'custom_tools'
framework_parent = Path(os.environ.get('SENTIENTMILK_FRAMEWORK_PARENT', root))
framework_dir = framework_parent / 'sentientmilk_framework'
ffmpeg_path = os.environ.get('MILKCHAN_FFMPEG_PATH')

print(f"[SPEC] Assets directory: {assets_dir}")
print(f"[SPEC] Framework directory: {framework_dir}")
print(f"[SPEC] Custom tools directory: {custom_tools_dir}")

# Collect custom tools
custom_tools_datas = []
if custom_tools_dir.exists():
    for py_file in custom_tools_dir.rglob('*.py'):
        rel_path = py_file.relative_to(root)
        custom_tools_datas.append((str(py_file), str(rel_path.parent)))
    print(f"[SPEC] Custom tools files: {len(custom_tools_datas)}")

ffmpeg_datas = []
if ffmpeg_path:
    ffmpeg_file = Path(ffmpeg_path)
    if ffmpeg_file.exists():
        ffmpeg_datas.append((str(ffmpeg_file), 'bin'))
        print(f"[SPEC] Bundled FFmpeg: {ffmpeg_file}")

framework_hiddenimports = []
if framework_dir.exists():
    if str(framework_parent) not in sys.path:
        sys.path.insert(0, str(framework_parent))
    framework_hiddenimports = collect_submodules('sentientmilk_framework')
    if not framework_hiddenimports:
        framework_hiddenimports = [
            'sentientmilk_framework',
            'sentientmilk_framework.ai',
            'sentientmilk_framework.exceptions',
            'sentientmilk_framework.types',
            'sentientmilk_framework.tools',
            'sentientmilk_framework.tools.delete',
            'sentientmilk_framework.tools.edit',
            'sentientmilk_framework.tools.exec',
            'sentientmilk_framework.tools.read',
            'sentientmilk_framework.tools.web_search',
            'sentientmilk_framework.tools.write',
        ]
    print(f"[SPEC] Framework modules: {len(framework_hiddenimports)}")
else:
    raise SystemExit(
        "SentientMilk framework not found. Run build.sh so it can clone "
        "https://github.com/obezbolen67/SentientMilk.git first."
    )

a = Analysis(
    ['milkchan/main.py'],
    pathex=[str(framework_parent)],
    binaries=[],
    datas=[
        # Bundle assets (will be extracted to sys._MEIPASS/assets)
        (str(assets_dir), 'assets'),
    ] + custom_tools_datas + ffmpeg_datas,
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
        # Custom tools
        'milkchan.custom_tools',
        'milkchan.custom_tools.update_sprite',
        'milkchan.custom_tools.memory',
        'milkchan.custom_tools.take_screenshot',
    ] + framework_hiddenimports,
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
        'pytest',
        'py',
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
