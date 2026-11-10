import importlib.util
import inspect
from pathlib import Path

import pytest


def load_installer_module():
    path = Path(__file__).parents[1] / "packaging/macos/install_macos.py"
    specification = importlib.util.spec_from_file_location(
        "giuli_macos_installer",
        path,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("machine", "expected"),
    [("arm64", ("arm64", "osx-arm64")), ("x86_64", ("x86_64", "osx-64"))],
)
def test_macos_installer_accepts_native_architectures(
    monkeypatch, machine: str, expected: tuple[str, str]
) -> None:
    installer = load_installer_module()
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(installer, "running_under_rosetta", lambda: False)
    monkeypatch.setattr(installer.platform, "machine", lambda: machine)
    monkeypatch.setattr(installer.platform, "mac_ver", lambda: ("13.0", (), ""))

    assert installer.detect_macos_platform() == expected


def test_macos_installer_rejects_rosetta(monkeypatch) -> None:
    installer = load_installer_module()
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(installer, "running_under_rosetta", lambda: True)

    with pytest.raises(installer.InstallerError, match="Rosetta"):
        installer.detect_macos_platform()


def test_macos_installer_rejects_unsupported_macos(monkeypatch) -> None:
    installer = load_installer_module()
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(installer, "running_under_rosetta", lambda: False)
    monkeypatch.setattr(installer.platform, "mac_ver", lambda: ("12.7.6", (), ""))

    with pytest.raises(installer.InstallerError, match="macOS 13.0"):
        installer.detect_macos_platform()


def test_macos_installer_provisions_private_python_and_lifecycle_commands() -> None:
    installer = load_installer_module()

    assert "python=3.12" in installer.RUNTIME_PACKAGES
    assert installer.GLOBAL_CLI.as_posix() == "/usr/local/bin/giuli"
    assert installer.UPDATER_COMMAND.as_posix() == "/usr/local/bin/giuli-update"
    assert installer.UNINSTALLER_COMMAND.as_posix() == "/usr/local/bin/giuli-uninstall"
    assert installer.APP_BUNDLE.as_posix() == "/Applications/GIULI.app"


def test_macos_installer_uses_release_source_as_a_regular_install() -> None:
    installer = load_installer_module()
    source = inspect.getsource(installer.install_python_application)
    rollback_source = inspect.getsource(installer.restore_previous_release)

    assert "--editable" not in source
    assert "--editable" not in rollback_source
    assert "packaging/macos/install_macos.py" in inspect.getsource(
        installer.install_updater
    )


def test_macos_documentation_exposes_automated_installation() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    manual = (root / "docs/USER_MANUAL.md").read_text(encoding="utf-8")

    for document in (readme, manual):
        assert "install_macos.py" in document
        assert "git clone https://github.com/EXCI5ION/giuli-nmr.git" in document
        assert "giuli-update" in document
        assert "giuli-uninstall" in document


