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
framework_parent = Path(os.environ.get('SENTIENTMILK_FRAMEWORK_PARENT', root))
framework_dir = framework_parent / 'sentientmilk_framework'

print(f"[SPEC] Assets directory: {assets_dir}")
print(f"[SPEC] Framework directory: {framework_dir}")

if not (framework_dir / 'server.py').exists():
    raise SystemExit(
        "SentientMilk brain not found. Run build.sh so it can clone "
        "https://github.com/obezbolen67/SentientMilk.git first."
    )
if str(framework_parent) not in sys.path:
    sys.path.insert(0, str(framework_parent))
# Packaged MilkChan starts the brain as `MilkChan --serve-brain`: bundle all of it.
framework_hiddenimports = collect_submodules('sentientmilk_framework')
print(f"[SPEC] Framework modules: {len(framework_hiddenimports)}")

a = Analysis(
    ['milkchan/main.py'],
    pathex=[str(framework_parent)],
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
        'sqlite3',
        'requests',
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
