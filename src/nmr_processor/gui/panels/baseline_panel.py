from math import isfinite, log10

from PySide6.QtCore import (
    QSignalBlocker,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)


class AutomaticBaselinePanel(QGroupBox):
    """Vista previa interactiva de arPLS."""

    preview_requested = Signal(float)
    apply_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Línea de base automática (arPLS)",
            parent,
        )

        self.default_instruction_text = (
            "Ajusta λ para controlar la suavidad de la curva. "
            "Los valores altos producen líneas más rígidas."
        )
        self.instruction_label = QLabel(
            self.default_instruction_text
        )
        self.instruction_label.setWordWrap(True)

        # El control representa log10(lambda). Cada unidad
        # del slider equivale a 0.1 órdenes de magnitud.
        self.lambda_slider = QSlider(
            Qt.Orientation.Horizontal
        )
        self.lambda_slider.setRange(40, 90)
        self.lambda_slider.setSingleStep(1)
        self.lambda_slider.setPageStep(5)
        self.lambda_slider.setTickInterval(5)
        self.lambda_slider.setTickPosition(
            QSlider.TickPosition.TicksBelow
        )
        self.lambda_slider.setValue(50)

        self.lambda_label = QLabel()
        self.lambda_label.setMinimumWidth(125)

        self.preset_buttons: list[QPushButton] = []
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(
            QLabel("Valores rápidos")
        )

        for label, value in (
            ("1e5", 1e5),
            ("1e6", 1e6),
            ("1e7", 1e7),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, selected=value: (
                    self.set_lambda(selected)
                )
            )
            presets_layout.addWidget(button)
            self.preset_buttons.append(button)

        presets_layout.addStretch()

        self.cancel_button = QPushButton(
            "Cancelar"
        )
        self.apply_button = QPushButton(
            "Aplicar"
        )

        lambda_layout = QGridLayout()
        lambda_layout.addWidget(
            QLabel("Suavidad"),
            0,
            0,
        )
        lambda_layout.addWidget(
            self.lambda_slider,
            0,
            1,
        )
        lambda_layout.addWidget(
            self.lambda_label,
            0,
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
        main_layout.addWidget(
            self.instruction_label
        )
        main_layout.addLayout(
            lambda_layout
        )
        main_layout.addLayout(
            presets_layout
        )
        main_layout.addLayout(
            buttons_layout
        )

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(250)

        self.lambda_slider.valueChanged.connect(
            self.schedule_preview
        )
        self.preview_timer.timeout.connect(
            self.request_preview_now
        )
        self.cancel_button.clicked.connect(
            self.cancel_requested.emit
        )
        self.apply_button.clicked.connect(
            self.apply_requested.emit
        )

        self.update_lambda_label()
        self.set_preview_available(False)

    @property
    def lambda_value(self) -> float:
        """Devuelve λ a partir de la posición logarítmica."""

        exponent = (
            self.lambda_slider.value()
            / 10.0
        )
        return 10.0**exponent

    def set_lambda(
        self,
        value: float,
        request_preview: bool = True,
    ) -> None:
        """Establece λ dentro del rango disponible."""

        if not isfinite(value) or value <= 0:
            raise ValueError(
                "Lambda debe ser un valor positivo."
            )

        slider_value = round(
            10.0 * log10(value)
        )
        slider_value = max(
            self.lambda_slider.minimum(),
            min(
                slider_value,
                self.lambda_slider.maximum(),
            ),
        )

        blocker = QSignalBlocker(
            self.lambda_slider
        )
        self.lambda_slider.setValue(
            slider_value
        )
        del blocker

        self.update_lambda_label()

        if request_preview:
            self.preview_timer.start()

    def schedule_preview(self) -> None:
        """Posterga el cálculo hasta que el control se estabilice."""

        self.update_lambda_label()
        self.set_preview_available(False)
        self.preview_timer.start()

    def request_preview_now(self) -> None:
        """Solicita el cálculo para el valor actual."""

        self.preview_timer.stop()
        self.preview_requested.emit(
            self.lambda_value
        )

    def stop_pending_preview(self) -> None:
        """Cancela un recálculo que aún no comenzó."""

        self.preview_timer.stop()

    def set_batch_context(
        self,
        sample_count: int,
        preview_name: str,
        excluded_region_count: int = 0,
    ) -> None:
        """Explica cuándo la vista previa representa a un lote."""

        if sample_count <= 1:
            text = self.default_instruction_text
        else:
            text = (
                f"Vista previa sobre «{preview_name}». Ajusta λ; "
                f"al aplicar se usará el mismo valor en "
                f"{sample_count} espectros seleccionados."
            )

        if excluded_region_count:
            text += (
                f" Se ignorarán {excluded_region_count} zona(s) ciega(s) "
                "durante el ajuste; sus datos no se eliminarán."
            )

        self.instruction_label.setText(text)

    def update_lambda_label(self) -> None:
        """Muestra λ mediante notación científica."""

        self.lambda_label.setText(
            f"λ = {self.lambda_value:.2e}"
        )

    def set_preview_available(
        self,
        available: bool,
    ) -> None:
        """Habilita aplicar cuando existe un resultado válido."""

        self.apply_button.setEnabled(
            available
        )


class BaselinePanel(QGroupBox):
    """Controles para la corrección manual de línea de base."""

    settings_changed = Signal(int)
    remove_last_requested = Signal()
    clear_requested = Signal()
    apply_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Corrección manual de línea de base",
            parent,
        )

        self.instruction_label = QLabel(
            "Haz clic izquierdo sobre regiones sin señal "
            "para añadir puntos de línea de base."
        )
        self.instruction_label.setWordWrap(True)

        self.point_count_label = QLabel(
            "Puntos seleccionados: 0"
        )

        self.half_width_spin = QSpinBox()
        self.half_width_spin.setRange(0, 100)
        self.half_width_spin.setValue(8)
        self.half_width_spin.setSuffix(" puntos")
        self.half_width_spin.setToolTip(
            "Semiancho de la ventana utilizada para promediar "
            "la intensidad alrededor de cada punto."
        )

        self.remove_last_button = QPushButton(
            "Quitar último"
        )
        self.clear_button = QPushButton(
            "Borrar puntos"
        )
        self.cancel_button = QPushButton(
            "Cancelar"
        )
        self.apply_button = QPushButton(
            "Aplicar"
        )

        controls_layout = QGridLayout()
        controls_layout.addWidget(
            self.point_count_label,
            0,
            0,
        )
        controls_layout.addWidget(
            QLabel("Semiancho de los nodos"),
            0,
            1,
        )
        controls_layout.addWidget(
            self.half_width_spin,
            0,
            2,
        )

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(
            self.remove_last_button
        )
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

        self.half_width_spin.valueChanged.connect(
            self.settings_changed.emit
        )
        self.remove_last_button.clicked.connect(
            self.remove_last_requested.emit
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

        self.set_point_count(0)

    @property
    def half_width_points(self) -> int:
        """Devuelve el semiancho elegido para los nodos."""

        return self.half_width_spin.value()

    def set_point_count(self, count: int) -> None:
        """Actualiza el contador y los botones disponibles."""

        self.point_count_label.setText(
            f"Puntos seleccionados: {count}"
        )

        has_points = count > 0
        has_enough_points = count >= 2

        self.remove_last_button.setEnabled(
            has_points
        )
        self.clear_button.setEnabled(
            has_points
        )
        self.apply_button.setEnabled(
            has_enough_points
        )

    def set_preview_available(
        self,
        available: bool,
    ) -> None:
        """Habilita aplicar únicamente si la curva es válida."""

        self.apply_button.setEnabled(
            available
        )
