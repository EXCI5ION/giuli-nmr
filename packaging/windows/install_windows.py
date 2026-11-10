"""Instala, actualiza o elimina GIULI en Windows x64 y ARM64.

El instalador trabaja por usuario, no requiere Git ni privilegios de
administrador y obtiene siempre una release estable publicada en GitHub.
Debe ejecutarse con Python 3.12 o 3.13 de la misma arquitectura que Windows.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

APP_NAME = "GIULI"
REPOSITORY = "EXCI5ION/giuli-nmr"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
GITHUB_API = f"https://api.github.com/repos/{REPOSITORY}"
USER_AGENT = "GIULI-Windows-Installer"

LOCAL_APP_DATA = Path(
    os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
)
INSTALL_ROOT = LOCAL_APP_DATA / "GIULI"
VENV_DIR = INSTALL_ROOT / ".venv"
COMMAND_DIR = INSTALL_ROOT / "bin"
INSTALLED_INSTALLER = INSTALL_ROOT / "install_windows.py"
STATE_FILE = INSTALL_ROOT / "installation.json"

MINIMUM_PYTHON = (3, 12)
MAXIMUM_PYTHON = (3, 14)
STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SUPPORTED_ARCHITECTURES = frozenset({"AMD64", "ARM64"})


class InstallerError(RuntimeError):
    """Error esperado que puede mostrarse directamente al usuario."""


def print_step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def run(
    command: list[str],
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"    > {subprocess.list2cmdline(command)}", flush=True)
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
    )


def output(command: list[str], *, env: dict[str, str] | None = None) -> str:
    return run(command, capture=True, env=env).stdout.strip()


def normalized_architecture(value: str) -> str:
    aliases = {
        "amd64": "AMD64",
        "x86_64": "AMD64",
        "arm64": "ARM64",
        "aarch64": "ARM64",
    }
    return aliases.get(value.strip().casefold(), value.strip().upper())


def native_windows_architecture() -> str:
    raw_value = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get(
        "PROCESSOR_ARCHITECTURE", platform.machine()
    )
    return normalized_architecture(raw_value)


def validate_host() -> str:
    if sys.platform != "win32":
        raise InstallerError("Este instalador sólo puede ejecutarse en Windows.")
    version = sys.version_info[:2]
    if not MINIMUM_PYTHON <= version < MAXIMUM_PYTHON:
        raise InstallerError(
            "GIULI requiere Python >=3.12,<3.14; "
            f"se encontró Python {version[0]}.{version[1]}."
        )

    process_architecture = normalized_architecture(platform.machine())
    native_architecture = native_windows_architecture()
    if native_architecture not in SUPPORTED_ARCHITECTURES:
        raise InstallerError(
            "GIULI admite Windows x64 y ARM64; "
            f"se detectó {native_architecture}."
        )
    if process_architecture != native_architecture:
        raise InstallerError(
            f"Python es {process_architecture}, pero Windows es {native_architecture}. "
            "Instala Python 3.12 o 3.13 nativo para esa arquitectura."
        )
    return native_architecture


def github_json(endpoint: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{GITHUB_API}/{endpoint.lstrip('/')}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise InstallerError("GitHub devolvió una respuesta no válida.")
    return payload


def release_tag(requested_version: str | None) -> str:
    if requested_version is None:
        payload = github_json("releases/latest")
        tag = str(payload.get("tag_name", ""))
    else:
        tag = f"v{requested_version.removeprefix('v')}"
        if not STABLE_TAG.fullmatch(tag):
            raise InstallerError(
                f"Versión no válida: {requested_version}. Usa X.Y.Z."
            )
        payload = github_json(
            f"releases/tags/{urllib.parse.quote(tag, safe='')}"
        )
        tag = str(payload.get("tag_name", tag))

    if not STABLE_TAG.fullmatch(tag):
        raise InstallerError("La última release no tiene un tag estable X.Y.Z.")
    return tag


def _safe_archive_members(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        relative = Path(member.filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise InstallerError("La release contiene una ruta ZIP no segura.")
        if (member.external_attr >> 16) & 0o170000 == 0o120000:
            raise InstallerError("La release contiene un enlace simbólico no admitido.")
        target = (destination / relative).resolve()
        if target != root and root not in target.parents:
            raise InstallerError("La release intenta escribir fuera del destino.")


def download_release(tag: str, destination: Path) -> Path:
    print_step(f"Descargando GIULI {tag.removeprefix('v')}")
    encoded_tag = urllib.parse.quote(tag, safe="")
    archive_url = f"{REPOSITORY_URL}/archive/refs/tags/{encoded_tag}.zip"
    archive_path = destination / "giuli.zip"
    request = urllib.request.Request(
        archive_url,
        headers={"User-Agent": USER_AGENT},
    )
    with (
        urllib.request.urlopen(request, timeout=120) as response,
        archive_path.open("wb") as stream,
    ):
        shutil.copyfileobj(response, stream)

    source_parent = destination / "source"
    source_parent.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        _safe_archive_members(archive, source_parent)
        archive.extractall(source_parent)

    roots = [item for item in source_parent.iterdir() if item.is_dir()]
    if len(roots) != 1 or not (roots[0] / "pyproject.toml").is_file():
        raise InstallerError("No se encontró un proyecto GIULI válido en la release.")
    return roots[0]


def project_version(source: Path) -> str:
    try:
        data = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
        version = str(data["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        raise InstallerError("No se pudo leer la versión de GIULI.") from error
    if not STABLE_TAG.fullmatch(f"v{version}"):
        raise InstallerError(f"La versión del proyecto no es válida: {version}.")
    return version


def _managed_child(path: Path) -> Path:
    resolved_root = INSTALL_ROOT.resolve()
    resolved_path = path.resolve()
    if resolved_path.parent != resolved_root:
        raise InstallerError(f"Ruta de instalación no segura: {resolved_path}")
    return resolved_path


def remove_managed_child(path: Path) -> None:
    if not path.exists():
        return
    resolved_path = _managed_child(path)
    if resolved_path.is_dir():
        shutil.rmtree(resolved_path)
    else:
        resolved_path.unlink()


def move_managed_child(source: Path, destination: Path) -> None:
    resolved_source = _managed_child(source)
    resolved_destination = _managed_child(destination)
    if resolved_destination.exists():
        raise InstallerError(
            f"El destino de activación ya existe: {resolved_destination}"
        )
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        raise InstallerError("No se encontró PowerShell para activar el entorno.")
    script = (
        f"Move-Item -LiteralPath '{_powershell_quote(resolved_source)}' "
        f"-Destination '{_powershell_quote(resolved_destination)}'"
    )
    run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]
    )
    if resolved_source.exists() or not resolved_destination.is_dir():
        raise InstallerError("Windows no pudo activar el entorno de GIULI.")


def environment_python(environment: Path) -> Path:
    return environment / "Scripts" / "python.exe"


def environment_entrypoint(environment: Path) -> Path:
    return environment / "Scripts" / "giuli.exe"


def build_candidate_environment(
    source: Path,
    expected_version: str,
    expected_architecture: str,
) -> Path:
    print_step("Creando el entorno aislado")
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = _managed_child(INSTALL_ROOT / ".venv-candidate")
    remove_managed_child(candidate)
    run([sys.executable, "-m", "venv", str(candidate)])
    python = environment_python(candidate)
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ]
    )
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            str(source),
        ]
    )
    verify_environment(
        candidate,
        expected_version=expected_version,
        expected_architecture=expected_architecture,
    )
    return candidate


def verify_environment(
    environment: Path,
    *,
    expected_version: str,
    expected_architecture: str,
) -> None:
    print_step("Verificando la instalación candidata")
    python = environment_python(environment)
    entrypoint = environment_entrypoint(environment)
    if not python.is_file() or not entrypoint.is_file():
        raise InstallerError("El entorno no creó los ejecutables de GIULI.")

    variables = os.environ.copy()
    variables["QT_QPA_PLATFORM"] = "offscreen"
    variables["GIULI_RENDERER"] = "raster"
    code = (
        "import platform; "
        "from importlib.metadata import version; "
        "import nmrglue, numpy, pybaselines, pyqtgraph, scipy; "
        "from PySide6.QtCore import qVersion; "
        "from PySide6.QtWidgets import QApplication; "
        "from nmr_processor.gui.main_window import MainWindow; "
        "app=QApplication([]); window=MainWindow(); window.close(); "
        "print(version('giuli')); print(platform.machine()); print(qVersion())"
    )
    values = output([str(python), "-c", code], env=variables).splitlines()
    if len(values) < 3 or values[-3] != expected_version:
        raise InstallerError("La versión instalada no coincide con la release.")
    if normalized_architecture(values[-2]) != expected_architecture:
        raise InstallerError("La arquitectura del entorno instalado no coincide.")


def activate_candidate(candidate: Path) -> Path | None:
    print_step("Activando la nueva versión")
    backup = _managed_child(INSTALL_ROOT / ".venv-backup")
    remove_managed_child(backup)
    had_previous_environment = VENV_DIR.exists()
    if had_previous_environment:
        move_managed_child(VENV_DIR, backup)
    try:
        move_managed_child(candidate, VENV_DIR)
    except (InstallerError, OSError, subprocess.CalledProcessError):
        if had_previous_environment and backup.exists() and not VENV_DIR.exists():
            move_managed_child(backup, VENV_DIR)
        raise
    return backup if had_previous_environment else None


def finish_environment_replacement(backup: Path | None) -> None:
    if backup is not None:
        remove_managed_child(backup)


def rollback_environment_replacement(backup: Path | None) -> None:
    remove_managed_child(VENV_DIR)
    if backup is not None and backup.exists():
        move_managed_child(backup, VENV_DIR)


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(content, encoding="utf-8", newline="\r\n")
    temporary.replace(path)


def cmd_launcher(target: Path, arguments: str = "%*") -> str:
    return f'@echo off\n"{target}" {arguments}\n'


def _powershell_quote(value: Path | str) -> str:
    return str(value).replace("'", "''")


def create_shortcut(folder_name: str, target: Path, icon: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        raise InstallerError("No se encontró PowerShell para crear los accesos directos.")
    script = (
        f"$folder=[Environment]::GetFolderPath('{folder_name}');"
        "if (-not $folder) { throw 'No se encontró la carpeta de accesos directos.' };"
        "$shell=New-Object -ComObject WScript.Shell;"
        f"$shortcut=$shell.CreateShortcut((Join-Path $folder '{APP_NAME}.lnk'));"
        f"$shortcut.TargetPath='{_powershell_quote(target)}';"
        f"$shortcut.WorkingDirectory='{_powershell_quote(INSTALL_ROOT)}';"
        f"$shortcut.IconLocation='{_powershell_quote(icon)},0';"
        "$shortcut.Description='Procesamiento de espectros de RMN';"
        "$shortcut.Save()"
    )
    run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]
    )


def remove_shortcuts() -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        return
    script = (
        "foreach ($kind in @('Programs','Desktop')) {"
        "$folder=[Environment]::GetFolderPath($kind);"
        f"if ($folder) {{ Remove-Item -LiteralPath (Join-Path $folder '{APP_NAME}.lnk') "
        "-Force -ErrorAction SilentlyContinue }}"
        "}"
    )
    run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]
    )


def _path_parts(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _same_windows_path(first: str, second: Path | str) -> bool:
    return os.path.normcase(os.path.normpath(first)) == os.path.normcase(
        os.path.normpath(str(second))
    )


def update_user_path(*, remove: bool = False) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            current, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, value_type = "", winreg.REG_EXPAND_SZ
        parts = [
            part
            for part in _path_parts(str(current))
            if not _same_windows_path(part, COMMAND_DIR)
        ]
        if not remove:
            parts.append(str(COMMAND_DIR))
        winreg.SetValueEx(key, "Path", 0, value_type, ";".join(parts))

    try:
        import ctypes

        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF,
            0x001A,
            0,
            "Environment",
            0x0002,
            5000,
            ctypes.byref(result),
        )
    except (AttributeError, OSError):
        pass


def installed_icon() -> Path:
    candidates = tuple(
        VENV_DIR.glob("Lib/site-packages/nmr_processor/resources/giuli-icon.ico")
    )
    if not candidates:
        raise InstallerError("No se encontró el icono instalado de GIULI.")
    return candidates[0]


def install_integration(
    source: Path,
    *,
    create_desktop_shortcut: bool,
) -> None:
    print_step("Creando comandos y accesos directos")
    entrypoint = environment_entrypoint(VENV_DIR)
    write_text_atomic(COMMAND_DIR / "giuli.cmd", cmd_launcher(entrypoint))

    repository_installer = source / "packaging" / "windows" / "install_windows.py"
    installer_source = (
        repository_installer
        if repository_installer.is_file()
        else Path(__file__).resolve()
    )
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(installer_source, INSTALLED_INSTALLER)
    write_text_atomic(
        COMMAND_DIR / "giuli-update.cmd",
        cmd_launcher(Path(sys.executable), f'"{INSTALLED_INSTALLER}" --update %*'),
    )
    write_text_atomic(
        COMMAND_DIR / "giuli-uninstall.cmd",
        cmd_launcher(Path(sys.executable), f'"{INSTALLED_INSTALLER}" --uninstall %*'),
    )
    update_user_path()

    icon = installed_icon()
    create_shortcut("Programs", entrypoint, icon)
    if create_desktop_shortcut:
        create_shortcut("Desktop", entrypoint, icon)


def load_state() -> dict[str, Any]:
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_state(tag: str, version: str, architecture: str) -> None:
    payload = {
        "tag": tag,
        "version": version,
        "architecture": architecture,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_executable": sys.executable,
        "repository": REPOSITORY_URL,
    }
    write_text_atomic(
        STATE_FILE,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def install_release(
    tag: str,
    architecture: str,
    *,
    create_desktop_shortcut: bool,
    local_source: Path | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="giuli-windows-") as temporary:
        temporary_path = Path(temporary)
        source = (
            local_source.resolve()
            if local_source is not None
            else download_release(tag, temporary_path)
        )
        version = project_version(source)
        if local_source is None and tag != f"v{version}":
            raise InstallerError(
                f"El tag {tag} no coincide con la versión {version} del proyecto."
            )

        candidate = build_candidate_environment(
            source,
            expected_version=version,
            expected_architecture=architecture,
        )
        backup = activate_candidate(candidate)
        try:
            install_integration(
                source,
                create_desktop_shortcut=create_desktop_shortcut,
            )
            save_state(tag, version, architecture)
        except (InstallerError, OSError, subprocess.CalledProcessError):
            rollback_environment_replacement(backup)
            raise
        finish_environment_replacement(backup)

    print(f"\n{APP_NAME} {version} se instaló correctamente para {architecture}.")
    print("Abre una terminal nueva y ejecuta: giuli")
    print("Para actualizar: giuli-update")
    print("Para desinstalar: giuli-uninstall")


def uninstall(assume_yes: bool) -> None:
    if not INSTALL_ROOT.exists():
        print("GIULI no está instalado mediante el instalador por consola.")
        return
    if not assume_yes:
        if not sys.stdin.isatty():
            raise InstallerError("Usa --yes para desinstalar sin confirmación.")
        answer = input(
            "Se eliminará la instalación por consola de GIULI. "
            "Escribe DESINSTALAR para continuar: "
        )
        if answer != "DESINSTALAR":
            raise InstallerError("Desinstalación cancelada.")

    print_step("Eliminando GIULI")
    remove_shortcuts()
    update_user_path(remove=True)
    expected = (LOCAL_APP_DATA / "GIULI").resolve()
    if INSTALL_ROOT.resolve() != expected:
        raise InstallerError("La ruta de desinstalación no es segura.")
    shutil.rmtree(INSTALL_ROOT)
    print("GIULI fue desinstalado; los proyectos del usuario no se modificaron.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Instala, actualiza, repara o desinstala GIULI en Windows x64/ARM64."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true")
    mode.add_argument("--repair", action="store_true")
    mode.add_argument("--uninstall", action="store_true")
    parser.add_argument("--version", dest="release_version", metavar="X.Y.Z")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-desktop-shortcut", action="store_true")
    parser.add_argument("--source", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    try:
        architecture = validate_host()
        if args.uninstall:
            uninstall(args.yes)
            return 0

        state = load_state()
        if args.source is not None:
            source = args.source.expanduser().resolve()
            if not (source / "pyproject.toml").is_file():
                raise InstallerError("--source no contiene un proyecto GIULI válido.")
            version = project_version(source)
            tag = f"v{version}"
        elif args.repair and state.get("tag"):
            tag = str(state["tag"])
            source = None
        else:
            tag = release_tag(args.release_version)
            source = None

        if (
            args.update
            and state.get("tag") == tag
            and environment_entrypoint(VENV_DIR).is_file()
        ):
            print(f"GIULI ya está en la última versión estable: {tag}.")
            return 0

        install_release(
            tag,
            architecture,
            create_desktop_shortcut=not args.no_desktop_shortcut,
            local_source=source,
        )
        return 0
    except InstallerError as error:
        print(f"\nError: {error}", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as error:
        print(
            f"\nError: GitHub respondió HTTP {error.code}. "
            "Comprueba la conexión y la versión solicitada.",
            file=sys.stderr,
        )
        return 1
    except urllib.error.URLError as error:
        print(f"\nError de red: {error.reason}", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(f"\nError durante la instalación: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
