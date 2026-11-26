import importlib.util
import inspect
import ssl
from pathlib import Path
from urllib import error as url_error

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


def test_macos_launcher_quotes_paths_and_forwards_arguments() -> None:
    installer = load_installer_module()

    launcher = installer.runtime_launcher()

    assert launcher.splitlines() == [
        "#!/bin/sh",
        f"exec '{installer.RUNTIME_PYTHON}' -m nmr_processor.app \"$@\"",
    ]
    assert "bin/giuli" not in launcher.replace("\\", "/")


def test_macos_maintenance_commands_use_private_python() -> None:
    installer = load_installer_module()

    for option in ("--update", "--uninstall"):
        launcher = installer.maintenance_launcher(option)
        assert launcher.splitlines() == [
            "#!/bin/sh",
            (
                f"exec '{installer.RUNTIME_PYTHON}' '{installer.INSTALLED_INSTALLER}' "
                f'{option} "$@"'
            ),
        ]


def test_macos_installer_explains_missing_https_certificates() -> None:
    installer = load_installer_module()
    ssl_error = ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED")

    message = str(installer.micromamba_download_error(url_error.URLError(ssl_error)))

    assert "certificados HTTPS" in message
    assert "Install Certificates.command" in message


def test_macos_installer_validates_every_generated_launcher(monkeypatch) -> None:
    installer = load_installer_module()
    commands: list[list[str]] = []

    monkeypatch.setattr(
        installer,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    installer.verify_launchers()

    assert commands == [
        ["/bin/sh", "-n", str(path)]
        for path in (
            installer.APP_EXECUTABLE,
            installer.GLOBAL_CLI,
            installer.GLOBAL_GUI,
            installer.UPDATER_COMMAND,
            installer.UNINSTALLER_COMMAND,
        )
    ]


def test_external_macos_installer_keeps_itself_for_maintenance(
    monkeypatch, tmp_path: Path
) -> None:
    installer = load_installer_module()
    installed = tmp_path / "support/install_macos.py"
    release = tmp_path / "source/packaging/macos/install_macos.py"
    external = tmp_path / "copied/install_macos.py"
    release.parent.mkdir(parents=True)
    release.write_text("release", encoding="utf-8")
    monkeypatch.setattr(installer, "INSTALLED_INSTALLER", installed)
    monkeypatch.setattr(installer, "SOURCE_DIR", tmp_path / "source")

    assert installer.select_installer_source(external) == external.resolve()
    assert installer.select_installer_source(installed) == release.resolve()


def test_macos_installer_uses_release_source_as_a_regular_install() -> None:
    installer = load_installer_module()
    source = inspect.getsource(installer.install_python_application)
    rollback_source = inspect.getsource(installer.restore_previous_release)

    assert "--editable" not in source
    assert "--editable" not in rollback_source
    assert "packaging/macos/install_macos.py" in inspect.getsource(
        installer.select_installer_source
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


