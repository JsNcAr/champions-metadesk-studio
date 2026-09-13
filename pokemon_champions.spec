# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for Champions MetaDesk Studio.

Build command (Linux):
    poetry run pyinstaller pokemon_champions.spec --noconfirm --clean

Build command (Windows):
    poetry run pyinstaller pokemon_champions.spec --noconfirm --clean
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect bundled data files (seed data, templates, reference data)
datas = [
    ('src/pokemon_champions_planning_tool/data', 'pokemon_champions_planning_tool/data'),
    ('src/pokemon_champions_planning_tool/domain/damage/reference_data.json', 'pokemon_champions_planning_tool/domain/damage'),
]

binaries = []

# Ensure dynamic SQLModel / SQLAlchemy / Flet modules are included
hiddenimports = [
    'sqlmodel',
    'sqlalchemy',
    'sqlalchemy.ext.baked',
    'pydantic',
    'flet',
    'flet_desktop',
    'requests',
    'bs4',
    'pokemon_champions_planning_tool',
]

# Collect all dynamic assets and binary drivers for Flet and Flet Desktop
flet_datas, flet_binaries, flet_hiddenimports = collect_all('flet')
datas.extend(flet_datas)
binaries.extend(flet_binaries)
hiddenimports.extend(flet_hiddenimports)

try:
    fd_datas, fd_binaries, fd_hiddenimports = collect_all('flet_desktop')
    datas.extend(fd_datas)
    binaries.extend(fd_binaries)
    hiddenimports.extend(fd_hiddenimports)
except Exception:
    pass

a = Analysis(
    ['src/pokemon_champions_planning_tool/main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ChampionsMetaDeskStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True if console output is desired for debugging
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
