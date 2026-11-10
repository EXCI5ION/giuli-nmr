import importlib.util
import zipfile
from pathlib import Path

import pytest


def load_installer():
    path = (
        Path(__file__).parents[1]
        / "packaging"
        / "windows"
        / "install_windows.py"
    )
    spec = importlib.util.spec_from_file_location("giuli_windows_installer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_installer_accepts_native_x64_and_arm64(monkeypatch) -> None:
    installer = load_installer()
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)

    monkeypatch.setattr(installer.platform, "machine", lambda: "AMD64")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    assert installer.validate_host() == "AMD64"

    monkeypatch.setattr(installer.platform, "machine", lambda: "ARM64")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "ARM64")
    assert installer.validate_host() == "ARM64"


def test_windows_installer_rejects_emulated_python(monkeypatch) -> None:
    installer = load_installer()
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.platform, "machine", lambda: "AMD64")
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "ARM64")

    with pytest.raises(installer.InstallerError, match="Python es AMD64"):
        installer.validate_host()


def test_windows_installer_rejects_unsafe_zip_paths(tmp_path: Path) -> None:
    installer = load_installer()
    archive_path = tmp_path / "release.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")

    with (
        zipfile.ZipFile(archive_path) as archive,
        pytest.raises(installer.InstallerError, match="ZIP no segura"),
    ):
        installer._safe_archive_members(archive, tmp_path / "source")


def test_windows_installer_launchers_expose_lifecycle_commands() -> None:
    installer = load_installer()
    launcher = installer.cmd_launcher(Path("C:/GIULI/giuli.exe"))

    assert launcher.startswith("@echo off")
    assert "giuli.exe" in launcher
    assert launcher.rstrip().endswith("%*")
    source = Path(installer.__file__).read_text(encoding="utf-8")
    assert 'COMMAND_DIR / "giuli.cmd"' in source
    assert 'COMMAND_DIR / "giuli-update.cmd"' in source
    assert 'COMMAND_DIR / "giuli-uninstall.cmd"' in source
    assert 'create_shortcut("Programs"' in source
    assert 'create_shortcut("Desktop"' in source


def test_environment_replacement_can_roll_back(tmp_path: Path, monkeypatch) -> None:
    installer = load_installer()
    root = tmp_path / "GIULI"
    current = root / ".venv"
    candidate = root / ".venv-candidate"
    current.mkdir(parents=True)
    candidate.mkdir()
    (current / "version.txt").write_text("previous", encoding="utf-8")
    (candidate / "version.txt").write_text("candidate", encoding="utf-8")
    monkeypatch.setattr(installer, "INSTALL_ROOT", root)
    monkeypatch.setattr(installer, "VENV_DIR", current)
    monkeypatch.setattr(
        installer,
        "move_managed_child",
        lambda source, destination: source.rename(destination),
    )

    backup = installer.activate_candidate(candidate)
    assert backup is not None
    assert (current / "version.txt").read_text(encoding="utf-8") == "candidate"

    installer.rollback_environment_replacement(backup)
    assert (current / "version.txt").read_text(encoding="utf-8") == "previous"


def test_runtime_ranges_include_windows_arm64_wheel_versions() -> None:
    pyproject = (
        Path(__file__).parents[1] / "pyproject.toml"
    ).read_text(encoding="utf-8")

    assert '"numpy>=2.3,<2.4"' in pyproject
    assert '"scipy>=1.16.2,<1.17"' in pyproject
    assert '"PySide6==6.11.2"' in pyproject


def test_release_build_copies_console_installers_as_assets() -> None:
    script = (
        Path(__file__).parents[1]
        / "packaging"
        / "windows"
        / "build_release.ps1"
    ).read_text(encoding="utf-8")

    assert 'Join-Path $releaseOutput "install_windows.py"' in script
    assert "Copy-Item -LiteralPath $consoleInstaller" in script
    assert 'Join-Path $releaseOutput "install_macos.py"' in script
    assert "Copy-Item -LiteralPath $macosInstaller" in script
