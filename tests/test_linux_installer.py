import importlib.util
import sys
from pathlib import Path


def load_installer_module():
    path = Path(__file__).parents[1] / "packaging/linux/install_linux.py"
    specification = importlib.util.spec_from_file_location(
        "giuli_linux_installer",
        path,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_linux_installer_recognizes_debian_derivatives(tmp_path) -> None:
    installer = load_installer_module()
    release = tmp_path / "os-release"
    release.write_text(
        'NAME="Distribución de prueba"\nID=antix\nID_LIKE="debian"\n',
        encoding="utf-8",
    )

    values = installer.parse_os_release(release)

    assert values["ID"] == "antix"
    assert "debian" in values["ID_LIKE"]


def test_linux_installer_accepts_the_supported_python_range() -> None:
    installer = load_installer_module()

    assert installer.MINIMUM_PYTHON == (3, 12)
    assert installer.MAXIMUM_PYTHON == (3, 14)
    assert installer.python_version(Path(sys.executable)) == sys.version_info[:2]


def test_linux_installer_creates_global_launchers_in_standard_paths() -> None:
    installer = load_installer_module()

    assert installer.GLOBAL_COMMAND.as_posix() == "/usr/local/bin/giuli"
    assert installer.UPDATER_COMMAND.as_posix() == "/usr/local/bin/giuli-update"
    assert "Exec=/usr/local/bin/giuli" in installer.desktop_entry()
