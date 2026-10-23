# -*- mode: python ; coding: utf-8 -*-

import sys


qt_excludes = [
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtNetworkAuth",
    "PySide6.QtSql",
    "PySide6.QtSensors",
    # Development-time UI/test bindings are not used by the application.
    "PySide6.QtTest",
    "PySide6.QtUiTools",
]

a = Analysis(
    ["src/qckdrw/main.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=qt_excludes,
    noarchive=False,
    optimize=0,
)

# Qt's hooks collect qtbase translation catalogs for QtCore/QtGui/QtWidgets.
# Quick Canvas has no localized UI or translator installation, so these catalogs
# cannot affect its English-only runtime. Keep all Qt plugins (especially the
# platform and image-format plugins) and linked Qt libraries intact.
def is_qt_translation(entry):
    destination = entry[0].replace("\\", "/")
    return destination.endswith(".qm") and (
        destination.startswith("PySide6/translations/")
        or destination.startswith("PySide6/Qt/translations/")
    )


a.datas = [entry for entry in a.datas if not is_qt_translation(entry)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="qckdrw",
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
)

app_files = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="qckdrw",
)

if sys.platform == "darwin":
    app = BUNDLE(
        app_files,
        name="Quick Canvas.app",
        icon=None,
        bundle_identifier="com.qckdrw.canvas",
        info_plist={"LSUIElement": True},
    )
