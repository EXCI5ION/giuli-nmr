from PySide6.QtCore import (
    QSignalBlocker,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)


class PhasePanel(QGroupBox):
    """Controles para la corrección manual de fase."""

    phase_changed = Signal(
        float,
        float,
        float,
    )

    apply_requested = Signal()
    cancel_requested = Signal()

    def __init__(
        self,
        parent=None,
    ) -> None:
        super().__init__(
            "Corrección manual de fase",
            parent,
        )

        self.create_phase_zero_controls()
        self.create_phase_first_controls()
        self.create_pivot_control()
        self.create_buttons()
        self.create_layout()
        self.connect_signals()

    def create_phase_zero_controls(self) -> None:
        """Crea los controles de fase de orden cero."""

        self.phase_zero_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.phase_zero_slider.setRange(
            -1800,
            1800,
        )

        self.phase_zero_spin = QDoubleSpinBox()
        self.phase_zero_spin.setRange(
            -180.0,
            180.0,
        )
        self.phase_zero_spin.setDecimals(1)
        self.phase_zero_spin.setSingleStep(0.1)
        self.phase_zero_spin.setSuffix("°")

    def create_phase_first_controls(self) -> None:
        """Crea los controles de fase de primer orden."""

        self.phase_first_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.phase_first_slider.setRange(
            -36000,
            36000,
        )

        self.phase_first_spin = QDoubleSpinBox()
        self.phase_first_spin.setRange(
            -3600.0,
            3600.0,
        )
        self.phase_first_spin.setDecimals(1)
        self.phase_first_spin.setSingleStep(1.0)
        self.phase_first_spin.setSuffix("°")

    def create_pivot_control(self) -> None:
        """Crea el control del pivote expresado en ppm."""

        self.pivot_spin = QDoubleSpinBox()
        self.pivot_spin.setRange(
            -20.0,
            20.0,
        )
        self.pivot_spin.setDecimals(4)
        self.pivot_spin.setSingleStep(0.01)
        self.pivot_spin.setSuffix(" ppm")
        self.pivot_spin.setValue(4.7)

    def create_buttons(self) -> None:
        """Crea los botones del panel."""

        self.apply_button = QPushButton(
            "Aplicar"
        )

        self.cancel_button = QPushButton(
            "Cancelar"
        )

    def create_layout(self) -> None:
        """Organiza visualmente los controles."""

        controls_layout = QGridLayout()

        controls_layout.addWidget(
            QLabel("Fase cero"),
            0,
            0,
        )
        controls_layout.addWidget(
            self.phase_zero_slider,
            0,
            1,
        )
        controls_layout.addWidget(
            self.phase_zero_spin,
            0,
            2,
        )

        controls_layout.addWidget(
            QLabel("Primer orden"),
            1,
            0,
        )
        controls_layout.addWidget(
            self.phase_first_slider,
            1,
            1,
        )
        controls_layout.addWidget(
            self.phase_first_spin,
            1,
            2,
        )

        controls_layout.addWidget(
            QLabel("Pivote"),
            2,
            0,
        )
        controls_layout.addWidget(
            self.pivot_spin,
            2,
            1,
            1,
            2,
        )

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        buttons_layout.addWidget(
            self.cancel_button
        )
        buttons_layout.addWidget(
            self.apply_button
        )

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(
            controls_layout
        )
        main_layout.addLayout(
            buttons_layout
        )

    def connect_signals(self) -> None:
        """Conecta sliders, valores numéricos y botones."""

        self.phase_zero_slider.valueChanged.connect(
            self.update_phase_zero_from_slider
        )

        self.phase_zero_spin.valueChanged.connect(
            self.update_phase_zero_from_spin
        )

        self.phase_first_slider.valueChanged.connect(
            self.update_phase_first_from_slider
        )

        self.phase_first_spin.valueChanged.connect(
            self.update_phase_first_from_spin
        )

        self.pivot_spin.valueChanged.connect(
            self.emit_phase_changed
        )

        self.apply_button.clicked.connect(
            self.apply_requested.emit
        )

        self.cancel_button.clicked.connect(
            self.cancel_requested.emit
        )

    def update_phase_zero_from_slider(
        self,
        value: int,
    ) -> None:
        """Actualiza fase cero desde el slider."""

        self.phase_zero_spin.setValue(
            value / 10.0
        )

    def update_phase_zero_from_spin(
        self,
        value: float,
    ) -> None:
        """Actualiza el slider desde fase cero."""

        blocker = QSignalBlocker(
            self.phase_zero_slider
        )

        self.phase_zero_slider.setValue(
            round(value * 10.0)
        )

        del blocker

        self.emit_phase_changed()

    def update_phase_first_from_slider(
        self,
        value: int,
    ) -> None:
        """Actualiza primer orden desde el slider."""

        self.phase_first_spin.setValue(
            value / 10.0
        )

    def update_phase_first_from_spin(
        self,
        value: float,
    ) -> None:
        """Actualiza el slider desde primer orden."""

        blocker = QSignalBlocker(
            self.phase_first_slider
        )

        self.phase_first_slider.setValue(
            round(value * 10.0)
        )

        del blocker

        self.emit_phase_changed()

    def emit_phase_changed(self) -> None:
        """Emite los parámetros actuales."""

        self.phase_changed.emit(
            self.phase_zero_spin.value(),
            self.phase_first_spin.value(),
            self.pivot_spin.value(),
        )

    def set_ppm_range(
        self,
        minimum_ppm: float,
        maximum_ppm: float,
    ) -> None:
        """Adapta el pivote al rango del espectro activo."""

        lower = min(
            minimum_ppm,
            maximum_ppm,
        )

        upper = max(
            minimum_ppm,
            maximum_ppm,
        )

        self.pivot_spin.setRange(
            lower,
            upper,
        )

        current_pivot = (
            self.pivot_spin.value()
        )

        if not lower <= current_pivot <= upper:
            self.pivot_spin.setValue(
                (lower + upper) / 2.0
            )

    def set_parameters(
        self,
        phase_zero_deg: float = 0.0,
        phase_first_deg: float = 0.0,
        pivot_ppm: float = 4.7,
    ) -> None:
        """Establece los controles sin emitir cambios intermedios."""

        widgets = (
            self.phase_zero_slider,
            self.phase_zero_spin,
            self.phase_first_slider,
            self.phase_first_spin,
            self.pivot_spin,
        )

        blockers = tuple(
            QSignalBlocker(widget)
            for widget in widgets
        )

        self.phase_zero_slider.setValue(
            round(phase_zero_deg * 10.0)
        )

        self.phase_zero_spin.setValue(
            phase_zero_deg
        )

        self.phase_first_slider.setValue(
            round(phase_first_deg * 10.0)
        )

        self.phase_first_spin.setValue(
            phase_first_deg
        )

        self.pivot_spin.setValue(
            pivot_ppm
        )

        del blockers

        self.emit_phase_changed()