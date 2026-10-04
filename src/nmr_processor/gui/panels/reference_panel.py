from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from nmr_processor.core.referencing import ReferenceMode


class ReferencePanel(QGroupBox):
    """Controles para el referenciado químico manual."""

    settings_changed = Signal()
    clear_requested = Signal()
    apply_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Referenciado químico",
            parent,
        )

        self.instruction_label = QLabel(
            "Haz clic izquierdo sobre la referencia. Para un "
            "multiplete, utiliza el cursor exacto sobre su centro."
        )
        self.instruction_label.setWordWrap(True)

        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-100.0, 100.0)
        self.target_spin.setDecimals(4)
        self.target_spin.setSingleStep(0.001)
        self.target_spin.setSuffix(" ppm")
        self.target_spin.setValue(5.2300)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(
            "Posición exacta del cursor",
            "cursor",
        )
        self.mode_combo.addItem(
            "Máximo local",
            "local_maximum",
        )

        self.search_width_spin = QDoubleSpinBox()
        self.search_width_spin.setRange(
            0.0001,
            5.0,
        )
        self.search_width_spin.setDecimals(4)
        self.search_width_spin.setSingleStep(0.005)
        self.search_width_spin.setSuffix(" ppm")
        self.search_width_spin.setValue(0.0300)
        self.search_width_spin.setToolTip(
            "Semiancho de la región utilizada para buscar "
            "el máximo local."
        )

        self.observed_value_label = QLabel("—")
        self.shift_value_label = QLabel("—")

        self.clear_button = QPushButton(
            "Elegir nuevamente"
        )
        self.cancel_button = QPushButton(
            "Cancelar"
        )
        self.apply_button = QPushButton(
            "Aplicar"
        )

        controls_layout = QGridLayout()
        controls_layout.addWidget(
            QLabel("Valor de referencia"),
            0,
            0,
        )
        controls_layout.addWidget(
            self.target_spin,
            0,
            1,
        )
        controls_layout.addWidget(
            QLabel("Método de selección"),
            0,
            2,
        )
        controls_layout.addWidget(
            self.mode_combo,
            0,
            3,
        )
        controls_layout.addWidget(
            QLabel("Semiventana de búsqueda"),
            1,
            0,
        )
        controls_layout.addWidget(
            self.search_width_spin,
            1,
            1,
        )
        controls_layout.addWidget(
            QLabel("Posición observada"),
            1,
            2,
        )
        controls_layout.addWidget(
            self.observed_value_label,
            1,
            3,
        )
        controls_layout.addWidget(
            QLabel("Desplazamiento del eje"),
            2,
            2,
        )
        controls_layout.addWidget(
            self.shift_value_label,
            2,
            3,
        )

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(
            self.clear_button
        )
        buttons_layout.addStretch()
        buttons_layout.addWidget(
            self.cancel_button
        )
        buttons_layout.addWidget(
            self.apply_button
        )

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(
            self.instruction_label
        )
        main_layout.addLayout(
            controls_layout
        )
        main_layout.addLayout(
            buttons_layout
        )

        self.target_spin.valueChanged.connect(
            lambda _value: self.settings_changed.emit()
        )
        self.mode_combo.currentIndexChanged.connect(
            self.handle_mode_changed
        )
        self.search_width_spin.valueChanged.connect(
            lambda _value: self.settings_changed.emit()
        )
        self.clear_button.clicked.connect(
            self.clear_requested.emit
        )
        self.cancel_button.clicked.connect(
            self.cancel_requested.emit
        )
        self.apply_button.clicked.connect(
            self.apply_requested.emit
        )

        self.handle_mode_changed()
        self.reset_result()

    @property
    def target_ppm(self) -> float:
        """Devuelve el valor químico asignado."""

        return self.target_spin.value()

    @property
    def reference_mode(self) -> ReferenceMode:
        """Devuelve el método de selección actual."""

        return self.mode_combo.currentData()

    @property
    def search_half_width_ppm(self) -> float:
        """Devuelve la semiventana para buscar el máximo."""

        return self.search_width_spin.value()

    def handle_mode_changed(
        self,
        _index: int | None = None,
    ) -> None:
        """Habilita la ventana únicamente para máximo local."""

        uses_window = (
            self.reference_mode
            == "local_maximum"
        )
        self.search_width_spin.setEnabled(
            uses_window
        )
        self.settings_changed.emit()

    def set_result(
        self,
        observed_ppm: float,
        shift_ppm: float,
    ) -> None:
        """Muestra el resultado provisional."""

        self.observed_value_label.setText(
            f"{observed_ppm:.4f} ppm"
        )
        self.shift_value_label.setText(
            f"{shift_ppm:+.4f} ppm"
        )
        self.clear_button.setEnabled(True)
        self.apply_button.setEnabled(True)

    def reset_result(self) -> None:
        """Limpia la selección provisional."""

        self.observed_value_label.setText("—")
        self.shift_value_label.setText("—")
        self.clear_button.setEnabled(False)
        self.apply_button.setEnabled(False)
