#!/usr/bin/env python3
"""Instalador y actualizador global de GIULI para Debian y derivados.

Uso desde una copia clonada del repositorio::

    python3 packaging/linux/install_linux.py

El script utiliza exclusivamente la biblioteca estándar y solicita privilegios
mediante sudo cuando son necesarios. Instala siempre una versión estable con tag.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "GIULI"
REPOSITORY_URL = "https://github.com/EXCI5ION/giuli-nmr.git"
APP_DIR = Path("/opt/giuli-nmr")
VENV_DIR = APP_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
VENV_ENTRYPOINT = VENV_DIR / "bin" / "giuli"

GLOBAL_COMMAND = Path("/usr/local/bin/giuli")
UPDATER_COMMAND = Path("/usr/local/bin/giuli-update")
INSTALLED_INSTALLER = Path("/usr/local/lib/giuli/install_linux.py")
DESKTOP_FILE = Path("/usr/share/applications/giuli.desktop")
INSTALLED_ICON = Path("/usr/share/pixmaps/giuli.png")
PERSISTENT_CUSTOM_ICON = Path("/usr/local/share/giuli/custom-icon.png")
REPOSITORY_INSTALLER = APP_DIR / "packaging/linux/install_linux.py"
SOURCE_ICON = APP_DIR / "src/nmr_processor/resources/giuli-icon.png"

MINIMUM_PYTHON = (3, 12)
MAXIMUM_PYTHON = (3, 14)
STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

DEBIAN_PACKAGES = (
    "git",
    "python3",
    "python3-venv",
    "desktop-file-utils",
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-image0",
    "libxcb-keysyms1",
    "libxcb-randr0",
    "libxcb-render-util0",
    "libxcb-shape0",
    "libxcb-xfixes0",
    "libxcb-xinerama0",
    "libxcb-xkb1",
    "libxkbcommon-x11-0",
    "libegl1",
    "libgl1",
)


class InstallerError(RuntimeError):
    """Error esperado que puede presentarse directamente al usuario."""


def print_step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def run(
    command: list[str],
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
    show: bool = True,
) -> subprocess.CompletedProcess[str]:
    if show:
        print(f"    $ {shlex.join(command)}", flush=True)
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
    )


def output(command: list[str], *, show: bool = True) -> str:
    return run(command, capture=True, show=show).stdout.strip()


def parse_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise InstallerError("No se pudo leer /etc/os-release.") from error
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def require_debian_family() -> None:
    info = parse_os_release()
    identifiers = {info.get("ID", "").lower()}
    identifiers.update(info.get("ID_LIKE", "").lower().split())
    if not identifiers.intersection({"debian", "ubuntu"}):
        detected = info.get("PRETTY_NAME", info.get("ID", "desconocido"))
        raise InstallerError(
            "Este instalador admite Debian, Ubuntu y derivados con APT. "
            f"Sistema detectado: {detected}."
        )
    if shutil.which("apt-get") is None:
        raise InstallerError("No se encontró apt-get.")


def reexec_with_sudo() -> None:
    if os.geteuid() == 0:
        return
    sudo = shutil.which("sudo")
    if sudo is None:
        raise InstallerError(
            "Se necesitan privilegios administrativos y no se encontró sudo. "
            "En sistemas que usan su, inicia una sesión root y vuelve a ejecutar "
            "el instalador."
        )
    script = str(Path(__file__).resolve())
    print("Se solicitarán permisos administrativos para instalar GIULI.")
    os.execv(sudo, [sudo, sys.executable, script, *sys.argv[1:]])


def install_system_dependencies() -> None:
    print_step("Instalando dependencias del sistema")
    environment = os.environ.copy()
    environment["DEBIAN_FRONTEND"] = "noninteractive"
    run(["apt-get", "update"], env=environment)
    run(["apt-get", "install", "-y", *DEBIAN_PACKAGES], env=environment)


def python_version(python: Path) -> tuple[int, int]:
    try:
        value = output(
            [
                str(python),
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            show=False,
        )
        major, minor = value.split(".", 1)
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise InstallerError(
            f"No se pudo determinar la versión de {python}."
        ) from error


def select_system_python() -> Path:
    command = shutil.which("python3")
    if command is None:
        raise InstallerError("No se encontró el comando python3.")
    python = Path(command).resolve()
    version = python_version(python)
    if not MINIMUM_PYTHON <= version < MAXIMUM_PYTHON:
        raise InstallerError(
            f"GIULI requiere Python >=3.12,<3.14; se encontró "
            f"Python {version[0]}.{version[1]} en {python}."
        )
    try:
        run(
            [
                str(python),
                "-c",
                "import ssl, sqlite3, venv; print('Python completo')",
            ],
            capture=True,
            show=False,
        )
    except subprocess.CalledProcessError as error:
        raise InstallerError(
            "La instalación de Python no incluye ssl, sqlite3 o venv."
        ) from error
    return python


def repository_is_dirty() -> bool:
    status = output(
        [
            "git",
            "-C",
            str(APP_DIR),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ]
    )
    return bool(status)


def prepare_repository(*, quiet: bool = False) -> str | None:
    if not quiet:
        print_step("Preparando el repositorio de GIULI")
    previous_commit: str | None = None
    if APP_DIR.exists():
        if not (APP_DIR / ".git").is_dir():
            raise InstallerError(
                f"{APP_DIR} existe pero no es un repositorio Git de GIULI."
            )
        if repository_is_dirty():
            raise InstallerError(
                f"Hay modificaciones locales en {APP_DIR}; no se sobrescribirán."
            )
        previous_commit = output(
            ["git", "-C", str(APP_DIR), "rev-parse", "HEAD"],
            show=not quiet,
        )
    else:
        APP_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", REPOSITORY_URL, str(APP_DIR)])
    run(
        ["git", "-C", str(APP_DIR), "fetch", "--tags", "--prune", "origin"],
        capture=quiet,
        show=not quiet,
    )
    return previous_commit


def stable_tags(*, quiet: bool = False) -> list[tuple[tuple[int, int, int], str]]:
    tags = output(
        ["git", "-C", str(APP_DIR), "tag", "--list"],
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
                f"Versión no válida: {requested_version}. Usa X.Y.Z."
            )
        if tag not in {item[1] for item in stable_tags(quiet=quiet)}:
            raise InstallerError(f"La versión {tag} no existe en el repositorio.")
        return tag
    if repair and (APP_DIR / ".git").is_dir():
        current_tags = output(
            ["git", "-C", str(APP_DIR), "tag", "--points-at", "HEAD"],
            show=not quiet,
        ).splitlines()
        stable = [tag for tag in current_tags if STABLE_TAG.fullmatch(tag)]
        if stable:
            return max(
                stable,
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
    run(["git", "-C", str(APP_DIR), "switch", "--detach", tag])


def ensure_virtual_environment(system_python: Path) -> None:
    desired_version = python_version(system_python)
    recreate = False
    if VENV_PYTHON.is_file():
        try:
            recreate = python_version(VENV_PYTHON) != desired_version
        except InstallerError:
            recreate = True
    elif VENV_DIR.exists():
        recreate = True
    if recreate:
        print_step("Recreando el entorno virtual para la versión actual de Python")
        if VENV_DIR.resolve().parent != APP_DIR.resolve():
            raise InstallerError("La ruta del entorno virtual no es segura.")
        shutil.rmtree(VENV_DIR)
    if not VENV_PYTHON.is_file():
        run([str(system_python), "-m", "venv", str(VENV_DIR)])


def create_or_update_environment(
    system_python: Path,
    *,
    force_reinstall: bool,
) -> None:
    print_step("Creando y actualizando el entorno virtual")
    ensure_virtual_environment(system_python)
    run(
        [
            str(VENV_PYTHON),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
        ]
    )
    command = [
        str(VENV_PYTHON),
        "-m",
        "pip",
        "install",
        "--upgrade",
    ]
    if force_reinstall:
        command.append("--force-reinstall")
    command.append(str(APP_DIR))
    run(command)


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o755)
    temporary.replace(path)


def desktop_entry() -> str:
    return """[Desktop Entry]
Type=Application
Version=1.0
Name=GIULI
GenericName=Procesamiento de RMN
Comment=Procesamiento interactivo de espectros de RMN
Exec=/usr/local/bin/giuli
Icon=/usr/share/pixmaps/giuli.png
Terminal=false
Categories=Science;Education;
Keywords=GIULI;NMR;RMN;espectroscopia;metabolomica;
StartupNotify=true
"""


def install_integration(custom_icon: Path | None) -> None:
    print_step("Instalando comando, icono y lanzador")
    if not VENV_ENTRYPOINT.is_file():
        raise InstallerError("La instalación no creó el ejecutable de GIULI.")
    write_executable(
        GLOBAL_COMMAND,
        f"#!/bin/sh\nexec '{VENV_ENTRYPOINT}' \"$@\"\n",
    )
    if custom_icon is not None:
        PERSISTENT_CUSTOM_ICON.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(custom_icon, PERSISTENT_CUSTOM_ICON)
        PERSISTENT_CUSTOM_ICON.chmod(0o644)
    icon = PERSISTENT_CUSTOM_ICON if PERSISTENT_CUSTOM_ICON.is_file() else SOURCE_ICON
    if not icon.is_file():
        raise InstallerError(f"No se encontró el icono: {icon}")
    INSTALLED_ICON.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon, INSTALLED_ICON)
    INSTALLED_ICON.chmod(0o644)
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(desktop_entry(), encoding="utf-8")
    DESKTOP_FILE.chmod(0o644)


def install_updater() -> None:
    print_step("Instalando el actualizador")
    source = (
        REPOSITORY_INSTALLER
        if REPOSITORY_INSTALLER.is_file()
        else Path(__file__).resolve()
    )
    INSTALLED_INSTALLER.parent.mkdir(parents=True, exist_ok=True)
    if source != INSTALLED_INSTALLER.resolve():
        shutil.copy2(source, INSTALLED_INSTALLER)
    INSTALLED_INSTALLER.chmod(0o755)
    write_executable(
        UPDATER_COMMAND,
        "#!/bin/sh\n"
        f'exec /usr/bin/env python3 "{INSTALLED_INSTALLER}" --update "$@"\n',
    )


def update_desktop_database() -> None:
    command = shutil.which("update-desktop-database")
    if command:
        run([command, str(DESKTOP_FILE.parent)])


def installed_version(*, quiet: bool = False) -> str:
    return output(
        [
            str(VENV_PYTHON),
            "-c",
            "from importlib.metadata import version; print(version('giuli'))",
        ],
        show=not quiet,
    )


def installation_matches_release(expected_tag: str) -> bool:
    required = (
        APP_DIR / ".git",
        VENV_PYTHON,
        VENV_ENTRYPOINT,
        GLOBAL_COMMAND,
        UPDATER_COMMAND,
        DESKTOP_FILE,
        INSTALLED_ICON,
    )
    if not all(path.exists() for path in required):
        return False
    try:
        installed = installed_version(quiet=True)
        head = output(["git", "-C", str(APP_DIR), "rev-parse", "HEAD"], show=False)
        release = output(
            ["git", "-C", str(APP_DIR), "rev-list", "-n", "1", expected_tag],
            show=False,
        )
    except subprocess.CalledProcessError:
        return False
    return installed == expected_tag.removeprefix("v") and head == release


def verify_xcb_dependencies() -> None:
    plugins = list(
        VENV_DIR.glob(
            "lib/python*/site-packages/PySide6/Qt/plugins/platforms/libqxcb.so"
        )
    )
    if not plugins:
        raise InstallerError("No se encontró el plugin libqxcb.so de PySide6.")
    result = run(["ldd", str(plugins[0])], capture=True)
    missing = [line.strip() for line in result.stdout.splitlines() if "not found" in line]
    if missing:
        details = "\n".join(f"  {line}" for line in missing)
        raise InstallerError(f"Faltan bibliotecas para Qt/XCB:\n{details}")


def verify_python_imports() -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    code = (
        "import nmrglue, numpy, pyqtgraph, scipy; "
        "from PySide6.QtCore import qVersion; "
        "from PySide6.QtWidgets import QApplication; "
        "from nmr_processor.gui.main_window import MainWindow; "
        "app = QApplication([]); window = MainWindow(); window.close(); "
        "print('Qt', qVersion())"
    )
    run([str(VENV_PYTHON), "-c", code], capture=True, env=environment)


def verify_installation(expected_tag: str) -> None:
    print_step("Verificando la instalación")
    version = installed_version()
    expected = expected_tag.removeprefix("v")
    if version != expected:
        raise InstallerError(
            f"Se esperaba GIULI {expected}, pero se instaló {version}."
        )
    for path in (GLOBAL_COMMAND, UPDATER_COMMAND, DESKTOP_FILE, INSTALLED_ICON):
        if not path.is_file():
            raise InstallerError(f"Falta un archivo de integración: {path}")
    verify_xcb_dependencies()
    verify_python_imports()
    print(f"\n{APP_NAME} {version} se instaló correctamente.")
    print("Puedes iniciarlo desde el menú de aplicaciones o con: giuli")
    print("Puedes buscar actualizaciones con: giuli-update")


def restore_previous_release(previous_commit: str | None) -> None:
    if previous_commit is None:
        return
    print("\nLa instalación falló. Restaurando la revisión anterior...", file=sys.stderr)
    try:
        run(["git", "-C", str(APP_DIR), "switch", "--detach", previous_commit])
        if VENV_PYTHON.is_file():
            run(
                [
                    str(VENV_PYTHON),
                    "-m",
                    "pip",
                    "install",
                    "--force-reinstall",
                    str(APP_DIR),
                ]
            )
    except subprocess.CalledProcessError as error:
        print(f"No se pudo completar la restauración: {error}", file=sys.stderr)


def uninstall(assume_yes: bool) -> None:
    if not assume_yes:
        if not sys.stdin.isatty():
            raise InstallerError("Usa --yes para desinstalar sin confirmación.")
        answer = input(
            "Esto eliminará GIULI de /opt y sus lanzadores. "
            "Escribe DESINSTALAR para continuar: "
        )
        if answer != "DESINSTALAR":
            raise InstallerError("Desinstalación cancelada.")
    print_step("Desinstalando GIULI")
    for path in (
        GLOBAL_COMMAND,
        UPDATER_COMMAND,
        DESKTOP_FILE,
        INSTALLED_ICON,
        PERSISTENT_CUSTOM_ICON,
    ):
        path.unlink(missing_ok=True)
    if APP_DIR.exists():
        if APP_DIR.resolve() != Path("/opt/giuli-nmr"):
            raise InstallerError("La ruta de instalación no es segura.")
        shutil.rmtree(APP_DIR)
    INSTALLED_INSTALLER.unlink(missing_ok=True)
    update_desktop_database()
    print("GIULI fue desinstalado. Los documentos de usuario no se modificaron.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instala, actualiza, repara o desinstala GIULI en Debian y derivados."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true")
    mode.add_argument("--repair", action="store_true")
    mode.add_argument("--uninstall", action="store_true")
    parser.add_argument("--version", dest="release_version", metavar="X.Y.Z")
    parser.add_argument("requested_version", nargs="?", metavar="X.Y.Z")
    parser.add_argument("--icon", type=Path, help="utiliza un icono PNG alternativo")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    try:
        require_debian_family()
        reexec_with_sudo()
        if args.uninstall:
            uninstall(args.yes)
            return 0

        custom_icon = args.icon.expanduser().resolve() if args.icon else None
        if custom_icon is not None and not custom_icon.is_file():
            raise InstallerError(f"No se encontró el icono: {custom_icon}")
        if args.release_version and args.requested_version:
            raise InstallerError("Indica la versión una sola vez.")
        requested = args.release_version or args.requested_version

        existing_update = args.update and (APP_DIR / ".git").is_dir()
        if existing_update:
            try:
                current = installed_version(quiet=True)
            except subprocess.CalledProcessError:
                current = "desconocida"
            print(f"Versión instalada: {current}")
            print("Buscando versiones disponibles...")
            previous_commit = prepare_repository(quiet=True)
        else:
            install_system_dependencies()
            previous_commit = prepare_repository()

        target_tag = resolve_target_tag(
            requested,
            args.repair,
            quiet=existing_update,
        )
        if args.update and installation_matches_release(target_tag):
            print(f"GIULI ya está en la última versión estable: {target_tag}")
            return 0
        if existing_update:
            print(f"Nueva versión estable disponible: {target_tag}")
            install_system_dependencies()

        system_python = select_system_python()
        try:
            checkout_release(target_tag)
            create_or_update_environment(
                system_python,
                force_reinstall=args.repair,
            )
            install_integration(custom_icon)
            install_updater()
            update_desktop_database()
            verify_installation(target_tag)
        except (InstallerError, subprocess.CalledProcessError):
            restore_previous_release(previous_commit)
            raise
        return 0
    except InstallerError as error:
        print(f"\nError: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        command = (
            [str(item) for item in error.cmd]
            if isinstance(error.cmd, (list, tuple))
            else [str(error.cmd)]
        )
        print(
            f"\nError: el comando terminó con código {error.returncode}: "
            f"{shlex.join(command)}",
            file=sys.stderr,
        )
        if error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        return error.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
