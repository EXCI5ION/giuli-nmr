import tomllib
from pathlib import Path

from nmr_processor import __version__


def test_release_version_is_consistent_across_artifacts() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    installer = (root / "packaging/windows/giuli.iss").read_text(encoding="utf-8")
    windows_metadata = (
        root / "packaging/windows/version_info.txt"
    ).read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert __version__ == "1.0.0"
    assert pyproject["project"]["version"] == __version__
    assert f"version: {__version__}" in citation
    assert f'#define MyAppVersion "{__version__}"' in installer
    assert f"ProductVersion', '{__version__}'" in windows_metadata
    assert f"Versión actual: **{__version__}**" in readme
