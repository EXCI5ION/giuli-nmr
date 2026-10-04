from importlib.resources import files

from PySide6.QtCore import QSysInfo, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from nmr_processor import __release_date__, __version__

PROJECT_URL = "https://github.com/EXCI5ION/giuli-nmr"


class AboutDialog(QDialog):
    """Presenta identidad, versión y procedencia de GIULI."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Acerca de GIULI")
        self.setMinimumWidth(560)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_data = (
            files("nmr_processor")
            .joinpath("resources/giuli-icon.png")
            .read_bytes()
        )
        pixmap = QPixmap()
        pixmap.loadFromData(icon_data, "PNG")
        icon_label.setPixmap(
            pixmap.scaled(
                180,
                180,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        brand = QLabel("GIULI")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setStyleSheet("font-size: 30px; font-weight: 700;")
        visual_layout = QVBoxLayout()
        visual_layout.addWidget(icon_label)
        visual_layout.addWidget(brand)

        architecture = QSysInfo.currentCpuArchitecture() or "desconocida"
        information = QLabel(
            "<h2>GIULI</h2>"
            f"<p><b>Versión:</b> {__version__}<br>"
            f"<b>Arquitectura:</b> {architecture}<br>"
            f"<b>Released:</b> {__release_date__}</p>"
            "<p>Copyright © 2026 Gabriel Anderson.</p>"
            f'<p><a href="{PROJECT_URL}">Página del proyecto</a></p>'
        )
        information.setOpenExternalLinks(True)
        information.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )

        content_layout = QHBoxLayout()
        content_layout.addLayout(visual_layout)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        content_layout.addWidget(separator)
        content_layout.addWidget(information, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(content_layout)
        layout.addWidget(buttons)
