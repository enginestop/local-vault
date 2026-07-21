import os
import sys
from pathlib import Path

root = Path(SPECPATH)
datas = []
static = root / "localvault" / "static"
if static.is_dir():
    datas.append((str(static), "localvault/static"))

analysis = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="LocalVault",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="LocalVault",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="LocalVault.app",
        bundle_identifier="app.localvault",
        info_plist={"LSUIElement": True, "NSHighResolutionCapable": True},
    )
