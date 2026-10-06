# build.spec — PyInstaller single-file EXE for Cartier
# Usage: pyinstaller build.spec
#
# Requirements (install first):
#   pip install pywebview pyinstaller
#   pip install pywebview[qt]   ← on Windows, Qt backend is most reliable

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Bundle the entire ui/ folder so index.html is reachable at runtime
        (str(ROOT / "ui"), "ui"),
    ],
    hiddenimports=[
        # pywebview backend — include all so PyInstaller picks the right one
        "webview",
        "webview.platforms.winforms",   # Windows (Edge WebView2)
        "webview.platforms.cocoa",      # macOS
        "webview.platforms.gtk",        # Linux
        "webview.platforms.qt",         # Qt fallback (all platforms)
        "clr",                          # pythonnet — needed for winforms backend
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "email", "html", "http",
        "xmlrpc", "pydoc", "doctest", "pdb",
    ],
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
    name="Cartier",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,               # compress — shaves ~10 MB off the EXE
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no terminal window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # ── Windows-specific ────────────────────────────────────────────────────
    # icon="ui/icon.ico",   # uncomment + supply a .ico to set the EXE icon
    version=None,
    uac_admin=False,
)
