from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class BlindRegionsPanel(QWidget):
    """Controles para editar las exclusiones ppm de un conjunto."""

    add_region_requested = Signal()
    add_numeric_region_requested = Signal()
    remove_last_requested = Signal()
    clear_requested = Signal()
    apply_requested = Signal()
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        self.title_label = QLabel("Zonas ciegas")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.instructions_label = QLabel(
            "Ajusta el zoom y añade una región. Puedes mover sus "
            "bordes directamente sobre el espectro."
        )
        self.instructions_label.setWordWrap(True)
        self.count_label = QLabel("0 zonas definidas")

        edit_buttons = QHBoxLayout()
        self.add_button = QPushButton("Añadir región visible")
        self.numeric_button = QPushButton("Ingresar valores…")
        self.remove_button = QPushButton("Quitar última")
        self.clear_button = QPushButton("Limpiar")
        edit_buttons.addWidget(self.add_button)
        edit_buttons.addWidget(self.numeric_button)
        edit_buttons.addWidget(self.remove_button)
        edit_buttons.addWidget(self.clear_button)

        decision_buttons = QHBoxLayout()
        decision_buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancelar")
        self.apply_button = QPushButton("Aplicar")
        self.apply_button.setDefault(True)
        decision_buttons.addWidget(self.cancel_button)
        decision_buttons.addWidget(self.apply_button)

        layout.addWidget(self.title_label)
        layout.addWidget(self.instructions_label)
        layout.addWidget(self.count_label)
        layout.addLayout(edit_buttons)
        layout.addLayout(decision_buttons)

        self.add_button.clicked.connect(self.add_region_requested)
        self.numeric_button.clicked.connect(self.add_numeric_region_requested)
        self.remove_button.clicked.connect(self.remove_last_requested)
        self.clear_button.clicked.connect(self.clear_requested)
        self.apply_button.clicked.connect(self.apply_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)

    def set_region_count(self, count: int) -> None:
        suffix = "zona definida" if count == 1 else "zonas definidas"
        self.count_label.setText(f"{count} {suffix}")

    def set_processing_mask_mode(self, enabled: bool) -> None:
        """Distingue una máscara de procesado de una exclusión estadística."""

        if enabled:
            self.title_label.setText("Regiones ignoradas en ACME/arPLS")
            self.instructions_label.setText(
                "Estas regiones solo se omiten al estimar fase y línea de "
                "base; la señal original no se borra ni se excluye de análisis."
            )
        else:
            self.title_label.setText("Zonas ciegas")
            self.instructions_label.setText(
                "Ajusta el zoom y añade una región. Puedes mover sus "
                "bordes directamente sobre el espectro."
            )


class BlindRegionDialog(QDialog):
    """Solicita dos límites ppm verificables antes de dibujarlos."""

    def __init__(
        self,
        minimum_allowed: float,
        maximum_allowed: float,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Añadir zona ciega por valores")
        lower, upper = sorted((minimum_allowed, maximum_allowed))
        center = (lower + upper) / 2.0
        width = max((upper - lower) * 0.02, 0.001)
        self.first_spin = QDoubleSpinBox()
        self.second_spin = QDoubleSpinBox()
        for spin in (self.first_spin, self.second_spin):
            spin.setRange(lower, upper)
            spin.setDecimals(6)
            spin.setSuffix(" ppm")
        self.first_spin.setValue(max(lower, center - width / 2.0))
        self.second_spin.setValue(min(upper, center + width / 2.0))

        form = QFormLayout(self)
        form.addRow("Primer límite", self.first_spin)
        form.addRow("Segundo límite", self.second_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @property
    def region(self) -> tuple[float, float]:
        return tuple(sorted((self.first_spin.value(), self.second_spin.value())))
