from PySide6.QtCore import (
    QSignalBlocker,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class SpectrumAppearanceDialog(QDialog):
    """Configura el estilo persistente de las curvas espectrales."""

    def __init__(
        self,
        color: str,
        line_width: float,
        crosshair_color: str = "#374151",
        crosshair_line_width: float = 1.0,
        crosshair_opacity: float = 0.65,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apariencia del espectro")
        self._color = QColor(color)
        self._crosshair_color = QColor(crosshair_color)

        if not self._color.isValid():
            self._color = QColor("#205D7A")
        if not self._crosshair_color.isValid():
            self._crosshair_color = QColor("#374151")

        self.color_button = QPushButton()
        self.color_button.setToolTip(
            "Color utilizado en la vista de un espectro individual."
        )
        self.color_button.clicked.connect(self.choose_color)
        self._update_color_button()

        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setRange(0.5, 5.0)
        self.line_width_spin.setDecimals(1)
        self.line_width_spin.setSingleStep(0.1)
        self.line_width_spin.setSuffix(" px")
        self.line_width_spin.setValue(line_width)
        self.line_width_spin.setToolTip(
            "Se aplica a espectros individuales, superpuestos y apilados."
        )

        self.crosshair_color_button = QPushButton()
        self.crosshair_color_button.clicked.connect(self.choose_crosshair_color)
        self._update_crosshair_color_button()
        self.crosshair_line_width_spin = QDoubleSpinBox()
        self.crosshair_line_width_spin.setRange(0.5, 5.0)
        self.crosshair_line_width_spin.setDecimals(1)
        self.crosshair_line_width_spin.setSingleStep(0.1)
        self.crosshair_line_width_spin.setSuffix(" px")
        self.crosshair_line_width_spin.setValue(crosshair_line_width)
        self.crosshair_opacity_spin = QDoubleSpinBox()
        self.crosshair_opacity_spin.setRange(5.0, 100.0)
        self.crosshair_opacity_spin.setDecimals(0)
        self.crosshair_opacity_spin.setSingleStep(5.0)
        self.crosshair_opacity_spin.setSuffix(" %")
        self.crosshair_opacity_spin.setValue(crosshair_opacity * 100.0)

        controls = QGridLayout()
        controls.addWidget(QLabel("Color individual"), 0, 0)
        controls.addWidget(self.color_button, 0, 1)
        controls.addWidget(QLabel("Grosor de línea"), 1, 0)
        controls.addWidget(self.line_width_spin, 1, 1)
        controls.addWidget(QLabel("Color de la cruz"), 2, 0)
        controls.addWidget(self.crosshair_color_button, 2, 1)
        controls.addWidget(QLabel("Grosor de la cruz"), 3, 0)
        controls.addWidget(self.crosshair_line_width_spin, 3, 1)
        controls.addWidget(QLabel("Opacidad de la cruz"), 4, 0)
        controls.addWidget(self.crosshair_opacity_spin, 4, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(buttons)

    @property
    def spectrum_color(self) -> str:
        return self._color.name()

    @property
    def line_width(self) -> float:
        return self.line_width_spin.value()

    @property
    def crosshair_color(self) -> str:
        return self._crosshair_color.name()

    @property
    def crosshair_line_width(self) -> float:
        return self.crosshair_line_width_spin.value()

    @property
    def crosshair_opacity(self) -> float:
        return self.crosshair_opacity_spin.value() / 100.0

    def choose_color(self) -> None:
        """Solicita un color sin alterar el gráfico hasta aceptar."""

        selected = QColorDialog.getColor(
            self._color,
            self,
            "Color del espectro individual",
        )
        if not selected.isValid():
            return

        self._color = selected
        self._update_color_button()

    def _update_color_button(self) -> None:
        self.color_button.setText(self._color.name().upper())
        self.color_button.setStyleSheet(
            f"background-color: {self._color.name()}; color: white;"
        )

    def choose_crosshair_color(self) -> None:
        selected = QColorDialog.getColor(
            self._crosshair_color,
            self,
            "Color de la cruz de inspección",
        )
        if selected.isValid():
            self._crosshair_color = selected
            self._update_crosshair_color_button()

    def _update_crosshair_color_button(self) -> None:
        self.crosshair_color_button.setText(
            self._crosshair_color.name().upper()
        )
        self.crosshair_color_button.setStyleSheet(
            f"background-color: {self._crosshair_color.name()}; color: white;"
        )


class StackDisplayPanel(QGroupBox):
    """Controla la representación del conjunto espectral activo."""

    mode_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Conjunto espectral activo",
            parent,
        )

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(
            "Superpuesto",
            "overlay",
        )
        self.mode_combo.addItem(
            "Apilado",
            "stacked",
        )

        layout = QGridLayout(self)
        layout.addWidget(
            QLabel("Visualización"),
            0,
            0,
        )
        layout.addWidget(
            self.mode_combo,
            0,
            1,
            1,
            2,
        )
        self.mode_combo.currentIndexChanged.connect(
            self.emit_mode_changed
        )

    @property
    def display_mode(self) -> str:
        """Devuelve el modo asociado al selector."""

        return str(
            self.mode_combo.currentData()
        )

    def set_values(
        self,
        display_mode: str,
    ) -> None:
        """Carga el modo visual sin emitir un cambio."""

        mode_index = self.mode_combo.findData(
            display_mode
        )

        if mode_index < 0:
            raise ValueError(
                "El modo de visualización no es válido."
            )

        mode_blocker = QSignalBlocker(
            self.mode_combo
        )

        self.mode_combo.setCurrentIndex(
            mode_index
        )

        del mode_blocker

    def emit_mode_changed(self) -> None:
        """Notifica el modo y adapta los controles dependientes."""

        self.mode_changed.emit(
            self.display_mode
        )
