import os
import sys
from importlib.resources import files

import pyqtgraph as pg
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication


def configure_graphics_renderer(
    renderer: str | None = None,
    platform_name: str | None = None,
) -> bool:
    """Configura OpenGL en Windows, permitiendo una anulación explícita."""

    requested_renderer = (
        renderer
        if renderer is not None
        else os.environ.get("GIULI_RENDERER", "auto")
    ).strip().casefold()

    if requested_renderer not in {"auto", "opengl", "raster"}:
        requested_renderer = "auto"

    current_platform = platform_name or sys.platform
    use_opengl = requested_renderer == "opengl" or (
        requested_renderer == "auto" and current_platform == "win32"
    )
    pg.setConfigOption("useOpenGL", use_opengl)
    return use_opengl


def main() -> int:
    configure_graphics_renderer()
    application = QApplication(sys.argv)
    application.setApplicationName("GIULI")
    application.setApplicationDisplayName("GIULI")

    icon_data = files("nmr_processor").joinpath("resources/giuli-icon.png").read_bytes()
    icon_pixmap = QPixmap()
    icon_pixmap.loadFromData(icon_data, "PNG")
    application.setWindowIcon(QIcon(icon_pixmap))

    from nmr_processor.gui.main_window import MainWindow

    window = MainWindow()
    window.show()

    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
