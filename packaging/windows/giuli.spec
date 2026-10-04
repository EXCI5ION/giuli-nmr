from pathlib import Path

from PyInstaller.building.datastruct import TOC


project_root = Path(SPECPATH).resolve().parents[1]
source_root = project_root / "src"
resources_dir = source_root / "nmr_processor" / "resources"


def _is_foreign_icu(entry):
    destination, source, _typecode = entry
    name = Path(destination).name.lower()
    is_icu = name == "icuuc.dll" or (
        name.startswith("icudt") and name.endswith(".dll")
    )

    source_parts = {part.lower() for part in Path(source).parts}
    return is_icu and "pyside6" not in source_parts


a = Analysis(
    [str(source_root / "nmr_processor" / "app.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=[
        (str(resources_dir / "giuli-icon.png"), "nmr_processor/resources"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Qt puede resolverse contra una ICU encontrada en el PATH del equipo de compilación.
# Nunca se distribuye una ICU externa a PySide6 junto con GIULI.
a.binaries = TOC(entry for entry in a.binaries if not _is_foreign_icu(entry))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GIULI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(resources_dir / "giuli-icon.ico"),
    version=str(project_root / "packaging" / "windows" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GIULI",
)
