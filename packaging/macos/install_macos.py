#!/usr/bin/env python3
"""System-wide installer and updater for GIULI on macOS.

The installer supports native Apple Silicon (arm64) and Intel (x86_64) Macs.
It installs GIULI and Python 3.12 in an isolated directory, creates
/Applications/GIULI.app and provides compact update commands.

Typical use from a clone of the GIULI repository:

    python3 packaging/macos/install_macos.py

The script uses only the Python standard library before provisioning its own
runtime. It intentionally refuses to install from a process translated by
Rosetta so Python and Qt cannot be mixed across architectures.
"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib import request

APP_NAME = "GIULI"
REPOSITORY_URL = "https://github.com/EXCI5ION/giuli-nmr.git"

SUPPORT_DIR = Path("/Library/Application Support/GIULI")
SOURCE_DIR = SUPPORT_DIR / "source"
RUNTIME_DIR = SUPPORT_DIR / "runtime"
RUNTIME_PYTHON = RUNTIME_DIR / "bin/python"
RUNTIME_PIP = RUNTIME_DIR / "bin/pip"
RUNTIME_ENTRYPOINT = RUNTIME_DIR / "bin/giuli"

MAMBA_ROOT = SUPPORT_DIR / "mamba"
MICROMAMBA = SUPPORT_DIR / "tools/micromamba"
MICROMAMBA_PLATFORM_FILE = SUPPORT_DIR / "tools/platform"

APP_BUNDLE = Path("/Applications/GIULI.app")
APP_CONTENTS = APP_BUNDLE / "Contents"
APP_EXECUTABLE = APP_CONTENTS / "MacOS/GIULI"
APP_RESOURCES = APP_CONTENTS / "Resources"
APP_ICON = APP_RESOURCES / "GIULI.icns"
INFO_PLIST = APP_CONTENTS / "Info.plist"

GLOBAL_CLI = Path("/usr/local/bin/giuli")
GLOBAL_GUI = Path("/usr/local/bin/giuli-gui")
UPDATER_COMMAND = Path("/usr/local/bin/giuli-update")
UNINSTALLER_COMMAND = Path("/usr/local/bin/giuli-uninstall")
INSTALLED_INSTALLER = SUPPORT_DIR / "install_macos.py"
PERSISTENT_CUSTOM_ICON = SUPPORT_DIR / "custom-icon.png"

STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
MINIMUM_FREE_BYTES = 4 * 1024**3
MINIMUM_MACOS = (13, 0)

RUNTIME_PACKAGES = (
    "python=3.12",
    "pip",
)


class InstallerError(RuntimeError):
    """Expected installation error with a user-facing message."""


def print_step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def command_text(command: list[str]) -> str:
    return " ".join(subprocess.list2cmdline([item]) for item in command)


def run(
    command: list[str],
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
    show: bool = True,
) -> subprocess.CompletedProcess[str]:
    if show:
        print(f"    $ {command_text(command)}", flush=True)
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
    )


def output(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    show: bool = True,
) -> str:
    return run(command, capture=True, env=env, show=show).stdout.strip()


def running_under_rosetta() -> bool:
    result = subprocess.run(
        ["/usr/sbin/sysctl", "-in", "sysctl.proc_translated"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip() == "1"


def detect_macos_platform() -> tuple[str, str]:
    if sys.platform != "darwin":
        raise InstallerError("Este instalador solamente puede ejecutarse en macOS.")
    if running_under_rosetta():
        raise InstallerError(
            "Terminal o Python está ejecutándose mediante Rosetta. Abra una "
            "Terminal nativa y vuelva a ejecutar el instalador para evitar "
            "mezclar componentes Intel y Apple Silicon."
        )

    release = platform.mac_ver()[0]
    try:
        macos_version = tuple(int(part) for part in release.split(".")[:2])
    except ValueError as exc:
        raise InstallerError(f"No se pudo interpretar la versión de macOS: {release}") from exc
    if len(macos_version) < 2 or macos_version < MINIMUM_MACOS:
        minimum = ".".join(map(str, MINIMUM_MACOS))
        raise InstallerError(
            f"GIULI requiere macOS {minimum} o posterior; se detectó {release}."
        )

    machine = platform.machine().lower()
    if machine == "arm64":
        return machine, "osx-arm64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64", "osx-64"
    raise InstallerError(f"Arquitectura de Mac no compatible: {machine}")


def require_system_tools() -> None:
    missing = [name for name in ("git", "sips", "iconutil") if not shutil.which(name)]
    if missing:
        names = ", ".join(missing)
        raise InstallerError(
            f"Faltan herramientas de macOS: {names}. Ejecute "
            "'xcode-select --install', complete la instalación y vuelva a intentarlo."
        )


def reexec_with_sudo() -> None:
    if os.geteuid() == 0:
        return
    sudo = shutil.which("sudo")
    if sudo is None:
        raise InstallerError("Se necesitan privilegios administrativos y no se encontró sudo.")
    script = str(Path(__file__).resolve())
    print("Se solicitará la contraseña de la cuenta administradora de la Mac.")
    os.execv(sudo, [sudo, sys.executable, script, *sys.argv[1:]])


def verify_free_space() -> None:
    available = shutil.disk_usage("/Library").free
    if available < MINIMUM_FREE_BYTES:
        gib = available / 1024**3
        raise InstallerError(
            "GIULI necesita al menos 4 GiB libres durante la instalación; "
            f"hay {gib:.1f} GiB disponibles."
        )


def repository_is_dirty(*, quiet: bool = False) -> bool:
    status = output(
        [
            "git",
            "-C",
            str(SOURCE_DIR),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        show=not quiet,
    )
    return bool(status)


def prepare_repository(*, quiet: bool = False) -> str | None:
    if not quiet:
        print_step("Preparando el repositorio de GIULI")
    previous_commit: str | None = None
    if SOURCE_DIR.exists():
        if not (SOURCE_DIR / ".git").is_dir():
            raise InstallerError(
                f"{SOURCE_DIR} ya existe pero no es un repositorio Git de GIULI."
            )
        if repository_is_dirty(quiet=quiet):
            raise InstallerError(
                f"Hay modificaciones locales en {SOURCE_DIR}. La instalación se "
                "detuvo para no sobrescribirlas."
            )
        previous_commit = output(
            ["git", "-C", str(SOURCE_DIR), "rev-parse", "HEAD"],
            show=not quiet,
        )
    else:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", REPOSITORY_URL, str(SOURCE_DIR)], show=not quiet)
    run(
        ["git", "-C", str(SOURCE_DIR), "fetch", "--tags", "--prune", "origin"],
        capture=quiet,
        show=not quiet,
    )
    return previous_commit


def stable_tags(*, quiet: bool = False) -> list[tuple[tuple[int, int, int], str]]:
    tags = output(
        ["git", "-C", str(SOURCE_DIR), "tag", "--list"],
        show=not quiet,
    ).splitlines()
    parsed: list[tuple[tuple[int, int, int], str]] = []
    for tag in tags:
        match = STABLE_TAG.fullmatch(tag.strip())
        if match:
            parsed.append((tuple(map(int, match.groups())), tag.strip()))
    return sorted(parsed, reverse=True)


def resolve_target_tag(
    requested_version: str | None,
    repair: bool,
    *,
    quiet: bool = False,
) -> str:
    if requested_version:
        tag = f"v{requested_version.removeprefix('v')}"
        if not STABLE_TAG.fullmatch(tag):
            raise InstallerError(
                f"Versión no válida: {requested_version}. Use un formato como 1.0.1."
            )
        if tag not in {item[1] for item in stable_tags(quiet=quiet)}:
            raise InstallerError(f"La versión {tag} no existe en el repositorio.")
        return tag

    if repair and (SOURCE_DIR / ".git").is_dir():
        pointed = output(
            ["git", "-C", str(SOURCE_DIR), "tag", "--points-at", "HEAD"],
            show=not quiet,
        ).splitlines()
        current = [tag for tag in pointed if STABLE_TAG.fullmatch(tag)]
        if current:
            return max(
                current,
                key=lambda tag: tuple(
                    map(int, STABLE_TAG.fullmatch(tag).groups())  # type: ignore[union-attr]
                ),
            )

    tags = stable_tags(quiet=quiet)
    if not tags:
        raise InstallerError("No se encontró ninguna versión estable de GIULI.")
    return tags[0][1]


def checkout_release(tag: str) -> None:
    print_step(f"Seleccionando GIULI {tag.removeprefix('v')}")
    run(["git", "-C", str(SOURCE_DIR), "switch", "--detach", tag])


def micromamba_url(conda_platform: str) -> str:
    return f"https://micro.mamba.pm/api/micromamba/{conda_platform}/latest"


def download_micromamba(conda_platform: str) -> None:
    installed_platform = ""
    if MICROMAMBA_PLATFORM_FILE.is_file():
        installed_platform = MICROMAMBA_PLATFORM_FILE.read_text(
            encoding="utf-8"
        ).strip()
    if MICROMAMBA.is_file() and installed_platform == conda_platform:
        return

    print_step(f"Descargando micromamba para {conda_platform}")
    MICROMAMBA.parent.mkdir(parents=True, exist_ok=True)
    download_request = request.Request(
        micromamba_url(conda_platform),
        headers={"User-Agent": "GIULI-macOS-Installer/1"},
    )
    with tempfile.TemporaryDirectory(prefix="giuli-micromamba-") as temporary:
        archive = Path(temporary) / "micromamba.tar.bz2"
        try:
            with (
                request.urlopen(download_request, timeout=120) as response,
                archive.open("wb") as destination,
            ):
                shutil.copyfileobj(response, destination)
        except OSError as exc:
            raise InstallerError("No se pudo descargar micromamba.") from exc
        try:
            with tarfile.open(archive, mode="r:bz2") as package:
                member = package.getmember("bin/micromamba")
                source = package.extractfile(member)
                if source is None:
                    raise InstallerError("El paquete de micromamba está incompleto.")
                temporary_binary = MICROMAMBA.with_suffix(".new")
                with temporary_binary.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                temporary_binary.chmod(0o755)
                temporary_binary.replace(MICROMAMBA)
        except (tarfile.TarError, KeyError) as exc:
            raise InstallerError("No se pudo extraer micromamba.") from exc

    MICROMAMBA_PLATFORM_FILE.write_text(f"{conda_platform}\n", encoding="utf-8")
    MICROMAMBA_PLATFORM_FILE.chmod(0o644)


def mamba_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["MAMBA_ROOT_PREFIX"] = str(MAMBA_ROOT)
    environment["MAMBA_NO_BANNER"] = "1"
    return environment


def install_runtime(conda_platform: str, *, force_reinstall: bool) -> None:
    download_micromamba(conda_platform)
    print_step("Instalando el runtime privado de Python")
    if force_reinstall and RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR)
    operation = "install" if RUNTIME_PYTHON.is_file() else "create"
    run(
        [
            str(MICROMAMBA),
            operation,
            "--yes",
            "--channel-priority",
            "strict",
            "--channel",
            "conda-forge",
            "--platform",
            conda_platform,
            "--prefix",
            str(RUNTIME_DIR),
            *RUNTIME_PACKAGES,
        ],
        env=mamba_environment(),
    )
    for path in (RUNTIME_PYTHON, RUNTIME_PIP):
        if not path.is_file():
            raise InstallerError(f"El runtime no creó el ejecutable esperado: {path}")


def install_python_application(*, force_reinstall: bool) -> None:
    print_step("Instalando GIULI y sus dependencias Python")
    run(
        [
            str(RUNTIME_PYTHON),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ]
    )
    command = [
        str(RUNTIME_PYTHON),
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--upgrade",
    ]
    if force_reinstall:
        command.append("--force-reinstall")
    command.append(str(SOURCE_DIR))
    run(command)
    if not RUNTIME_ENTRYPOINT.is_file():
        raise InstallerError("La instalación Python no creó los ejecutables de GIULI.")


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o755)
    temporary.replace(path)


def runtime_launcher(entrypoint: Path) -> str:
    return (
        "#!/bin/sh\n"
        f"export PATH='{RUNTIME_DIR / 'bin'}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin\n"
        f"exec '{entrypoint}' \"$@\"\n"
    )


def select_icon(custom_icon: Path | None) -> Path:
    if custom_icon is not None:
        PERSISTENT_CUSTOM_ICON.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(custom_icon, PERSISTENT_CUSTOM_ICON)
        PERSISTENT_CUSTOM_ICON.chmod(0o644)
    if PERSISTENT_CUSTOM_ICON.is_file():
        return PERSISTENT_CUSTOM_ICON
    source = SOURCE_DIR / "src/nmr_processor/resources/giuli-icon.png"
    if not source.is_file():
        raise InstallerError(f"No se encontró el icono de GIULI: {source}")
    return source


def create_icns(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="giuli-icon-") as temporary:
        iconset = Path(temporary) / "GIULI.iconset"
        iconset.mkdir()
        variants = {
            "icon_16x16.png": 16,
            "icon_16x16@2x.png": 32,
            "icon_32x32.png": 32,
            "icon_32x32@2x.png": 64,
            "icon_128x128.png": 128,
            "icon_128x128@2x.png": 256,
            "icon_256x256.png": 256,
            "icon_256x256@2x.png": 512,
            "icon_512x512.png": 512,
            "icon_512x512@2x.png": 1024,
        }
        for name, size in variants.items():
            run(
                [
                    "sips",
                    "-s",
                    "format",
                    "png",
                    "-z",
                    str(size),
                    str(size),
                    str(source),
                    "--out",
                    str(iconset / name),
                ],
                capture=True,
            )
        temporary_icns = Path(temporary) / "GIULI.icns"
        run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(temporary_icns)]
        )
        shutil.copy2(temporary_icns, destination)
        destination.chmod(0o644)


def write_info_plist(version: str) -> None:
    data = {
        "CFBundleDevelopmentRegion": "es",
        "CFBundleDisplayName": "GIULI",
        "CFBundleExecutable": "GIULI",
        "CFBundleIconFile": "GIULI.icns",
        "CFBundleIdentifier": "org.excision.giuli",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "GIULI",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
    }
    INFO_PLIST.parent.mkdir(parents=True, exist_ok=True)
    with INFO_PLIST.open("wb") as stream:
        plistlib.dump(data, stream, fmt=plistlib.FMT_XML, sort_keys=True)
    INFO_PLIST.chmod(0o644)


def install_integration(custom_icon: Path | None, version: str) -> None:
    print_step("Creando GIULI.app y los comandos globales")
    APP_EXECUTABLE.parent.mkdir(parents=True, exist_ok=True)
    APP_RESOURCES.mkdir(parents=True, exist_ok=True)
    write_executable(APP_EXECUTABLE, runtime_launcher(RUNTIME_ENTRYPOINT))
    create_icns(select_icon(custom_icon), APP_ICON)
    write_info_plist(version)

    write_executable(GLOBAL_CLI, runtime_launcher(RUNTIME_ENTRYPOINT))
    write_executable(GLOBAL_GUI, runtime_launcher(APP_EXECUTABLE))

    codesign = shutil.which("codesign")
    if codesign:
        run(
            [codesign, "--force", "--sign", "-", str(APP_BUNDLE)],
            capture=True,
        )


def install_updater() -> None:
    print_step("Instalando los comandos de mantenimiento")
    source_installer = SOURCE_DIR / "packaging/macos/install_macos.py"
    source = source_installer if source_installer.is_file() else Path(__file__).resolve()
    if source.resolve() != INSTALLED_INSTALLER.resolve():
        shutil.copy2(source, INSTALLED_INSTALLER)
    INSTALLED_INSTALLER.chmod(0o755)
    write_executable(
        UPDATER_COMMAND,
        "#!/bin/sh\n"
        f"exec '{RUNTIME_PYTHON}' '{INSTALLED_INSTALLER}' --update \"$@\"\n",
    )
    write_executable(
        UNINSTALLER_COMMAND,
        "#!/bin/sh\n"
        f"exec '{RUNTIME_PYTHON}' '{INSTALLED_INSTALLER}' --uninstall \"$@\"\n",
    )


def installed_version(*, quiet: bool = False) -> str:
    return output(
        [
            str(RUNTIME_PYTHON),
            "-c",
            "from importlib.metadata import version; print(version('giuli'))",
        ],
        show=not quiet,
    )


def installation_matches_release(expected_tag: str) -> bool:
    required = (
        SOURCE_DIR / ".git",
        RUNTIME_PYTHON,
        RUNTIME_ENTRYPOINT,
        APP_EXECUTABLE,
        INFO_PLIST,
        GLOBAL_CLI,
        GLOBAL_GUI,
        UPDATER_COMMAND,
        UNINSTALLER_COMMAND,
        INSTALLED_INSTALLER,
    )
    if not all(path.exists() for path in required):
        return False
    try:
        installed = installed_version(quiet=True)
        head = output(
            ["git", "-C", str(SOURCE_DIR), "rev-parse", "HEAD"], show=False
        )
        release_commit = output(
            ["git", "-C", str(SOURCE_DIR), "rev-list", "-n", "1", expected_tag],
            show=False,
        )
    except subprocess.CalledProcessError:
        return False
    return installed == expected_tag.removeprefix("v") and head == release_commit


def report_already_current(target_tag: str) -> None:
    print(f"GIULI ya está en la última versión estable: {target_tag}")


def verify_cocoa_plugin() -> None:
    plugins = list(
        RUNTIME_DIR.glob(
            "lib/python*/site-packages/PySide6/Qt/plugins/platforms/libqcocoa.dylib"
        )
    )
    if not plugins:
        raise InstallerError("No se encontró el plugin gráfico Cocoa de PySide6.")


def verify_installation(expected_tag: str, expected_platform: str) -> None:
    print_step("Verificando la instalación")
    version = installed_version()
    expected = expected_tag.removeprefix("v")
    if version != expected:
        raise InstallerError(f"Se esperaba GIULI {expected}, pero se instaló {version}.")
    verify_cocoa_plugin()

    output(
        [
            str(RUNTIME_PYTHON),
            "-c",
            (
                "import numpy, scipy, pyqtgraph, PySide6, nmrglue, pybaselines; "
                "from PySide6.QtWidgets import QApplication; "
                "from nmr_processor.gui.main_window import MainWindow; "
                "app=QApplication([]); window=MainWindow(); window.close(); "
                "print('Dependencias y ventana principal de GIULI: OK')"
            ),
        ]
    )

    print(f"\nGIULI {version} se instaló correctamente para {expected_platform}.")
    print("Puede abrirlo desde Aplicaciones → GIULI o ejecutar: giuli-gui")
    print("Para actualizarlo: sudo giuli-update")
    print("Para desinstalarlo: sudo giuli-uninstall")


def restore_previous_release(previous_commit: str | None) -> None:
    if previous_commit is None:
        return
    print("\nLa instalación falló. Restaurando la revisión anterior...", file=sys.stderr)
    try:
        run(["git", "-C", str(SOURCE_DIR), "switch", "--detach", previous_commit])
        if RUNTIME_PYTHON.is_file():
            run(
                [
                    str(RUNTIME_PYTHON),
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "--force-reinstall",
                    str(SOURCE_DIR),
                ]
            )
    except (InstallerError, subprocess.CalledProcessError) as exc:
        print(f"No se pudo completar la restauración: {exc}", file=sys.stderr)


def confirm_uninstall(assume_yes: bool) -> None:
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise InstallerError("Use --yes para desinstalar sin confirmación interactiva.")
    answer = input(
        "Esto eliminará GIULI, GIULI.app y su runtime privado. "
        "Escriba DESINSTALAR para continuar: "
    )
    if answer != "DESINSTALAR":
        raise InstallerError("Desinstalación cancelada.")


def uninstall(assume_yes: bool) -> None:
    confirm_uninstall(assume_yes)
    print_step("Desinstalando GIULI")
    for path in (GLOBAL_CLI, GLOBAL_GUI, UPDATER_COMMAND, UNINSTALLER_COMMAND):
        path.unlink(missing_ok=True)
    if APP_BUNDLE.exists():
        shutil.rmtree(APP_BUNDLE)
    if SUPPORT_DIR.exists():
        shutil.rmtree(SUPPORT_DIR)
    print("GIULI fue desinstalado. Los proyectos y datos personales no se modificaron.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instala, actualiza, repara o desinstala GIULI en macOS."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--update", action="store_true", help="actualiza a la versión estable más reciente"
    )
    mode.add_argument(
        "--repair", action="store_true", help="reinstala y verifica todos los componentes"
    )
    mode.add_argument("--uninstall", action="store_true", help="desinstala GIULI")
    parser.add_argument(
        "--version",
        dest="release_version",
        metavar="X.Y.Z",
        help="instala una versión estable concreta",
    )
    parser.add_argument(
        "requested_version",
        nargs="?",
        metavar="X.Y.Z",
        help="versión concreta; forma abreviada utilizada por giuli-update",
    )
    parser.add_argument(
        "--icon",
        type=Path,
        help="utiliza un PNG alternativo como icono de GIULI.app",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirma operaciones no interactivas, como la desinstalación",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    try:
        architecture, conda_platform = detect_macos_platform()
        require_system_tools()
        reexec_with_sudo()

        if args.uninstall:
            uninstall(args.yes)
            return 0

        custom_icon = args.icon.expanduser().resolve() if args.icon else None
        if custom_icon is not None and not custom_icon.is_file():
            raise InstallerError(f"No se encontró el icono solicitado: {custom_icon}")
        if args.release_version and args.requested_version:
            raise InstallerError("Indique la versión una sola vez.")
        requested = args.release_version or args.requested_version

        existing_update = args.update and (SOURCE_DIR / ".git").is_dir()
        if existing_update:
            try:
                current_version = installed_version(quiet=True)
            except subprocess.CalledProcessError:
                current_version = "desconocida"
            print(f"Versión instalada: {current_version}")
            print("Buscando versiones disponibles...")
            previous_commit = prepare_repository(quiet=True)
        else:
            verify_free_space()
            previous_commit = prepare_repository()

        target_tag = resolve_target_tag(
            requested,
            args.repair,
            quiet=existing_update,
        )

        if args.update and installation_matches_release(target_tag):
            if custom_icon is not None:
                install_integration(custom_icon, target_tag.removeprefix("v"))
            report_already_current(target_tag)
            return 0

        if existing_update:
            print(f"Nueva versión estable disponible: {target_tag}")
            verify_free_space()

        try:
            checkout_release(target_tag)
            install_runtime(conda_platform, force_reinstall=args.repair)
            install_python_application(force_reinstall=args.repair)
            version = target_tag.removeprefix("v")
            install_integration(custom_icon, version)
            install_updater()
            verify_installation(target_tag, conda_platform)
        except (InstallerError, subprocess.CalledProcessError):
            restore_previous_release(previous_commit)
            raise

        print(f"Arquitectura detectada: {architecture}")
        return 0
    except InstallerError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        failed = (
            [str(item) for item in exc.cmd]
            if isinstance(exc.cmd, (list, tuple))
            else [str(exc.cmd)]
        )
        print(
            f"\nError: el comando terminó con código {exc.returncode}: "
            f"{command_text(failed)}",
            file=sys.stderr,
        )
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())

