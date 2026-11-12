# PyInstaller build recipe for macOS (.app) and Windows (folder with .exe).
#   python tools/export_onnx.py          (once: writes models/htdemucs.onnx)
#   pyinstaller --noconfirm Stm.spec
import os
import sys

from PyInstaller.utils.hooks import collect_all

root = SPECPATH
version = open(os.path.join(root, "VERSION")).read().strip()
model = os.path.join(root, "models", "htdemucs.onnx")
if not os.path.isfile(model):
    raise SystemExit("models/htdemucs.onnx is missing: run  python tools/export_onnx.py  first")

datas, binaries, hiddenimports = collect_all("imageio_ffmpeg")
d, b, h = collect_all("onnxruntime")
datas += d
binaries += b
hiddenimports += h
datas += [
    (os.path.join(root, "stm", "ui"), os.path.join("stm", "ui")),
    (os.path.join(root, "VERSION"), "."),
    (model, "models"),
]
hiddenimports += ["certifi"]

a = Analysis(
    [os.path.join(root, "Stm.py")],
    pathex=[root],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "_tkinter", "torch", "onnx", "matplotlib"],
)
pyz = PYZ(a.pure)
icon = os.path.join(root, "assets", "AppIcon.icns" if sys.platform == "darwin" else "icon.ico")

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Stm",
    console=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Stm")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Stm.app",
        icon=icon,
        bundle_identifier="com.yuvrajgarg.stm",
        version=version,
        info_plist={
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "CFBundleDisplayName": "Stm",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSRequiresAquaSystemAppearance": False,
        },
    )
