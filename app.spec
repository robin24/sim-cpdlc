# -*- mode: python ; coding: utf-8 -*-

import importlib.util
block_cipher = None

added_files = [
    ('assets/', 'assets'),  # Include the sounds folder
    # Add any other files/folders you need
]

# Locate SimConnect.dll next to the installed SimConnect package
_sc_spec = importlib.util.find_spec('SimConnect')
_sc_binaries = []
if _sc_spec and _sc_spec.origin:
    import os
    _sc_dll = os.path.join(os.path.dirname(_sc_spec.origin), 'SimConnect.dll')
    if os.path.isfile(_sc_dll):
        _sc_binaries = [(_sc_dll, 'SimConnect')]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=_sc_binaries,
    datas=added_files,
    hiddenimports=[
        'hoppie_connector',
        'src',
        'src.config',
        'src.logging_setup',
        'src.utils',
        'src.gui',
        'src.gui.dialogs',
        'src.model',
        'src.controller',
        'SimConnect',
    ],
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
    [],
    exclude_binaries=True,
    name='Sim-CPDLC',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version='version_info.txt'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Sim-CPDLC',
)
